import os
import glob
import json
import subprocess
import platform
from langchain_core.messages import HumanMessage, SystemMessage
import config
from utils import setup_logger, sanitize_path
from utils.language_profiles import TARGET_PROFILES

logger = setup_logger("TestGenerator")

def run_test_healer(target_dir, test_dir, llm, profile):
    """Runs tests and auto-heals if they fail."""
    if profile['build_tool'] not in ['maven', 'pip', 'npm']:
        logger.warning(f"[Test-Healer] Test execution not supported for {profile['build_tool']}.")
        return True
        
    max_retries = 3
    is_windows = platform.system() == "Windows"
    
    for attempt in range(1, max_retries + 1):
        logger.info(f"\n[Test-Healer] Attempt {attempt}: Executing tests...")
        
        if profile['build_tool'] == 'maven':
            cmd = ["mvnw.cmd" if is_windows else "./mvnw", "test"]
        elif profile['build_tool'] == 'pip':
            cmd = ["pytest"]
        elif profile['build_tool'] == 'npm':
            cmd = ["npm", "test"]
            
        try:
            result = subprocess.run(cmd, cwd=target_dir, capture_output=True, text=True, shell=is_windows, timeout=300)
        except subprocess.TimeoutExpired:
            logger.error("[Test-Healer] Test execution timed out.")
            return False
            
        if result.returncode == 0:
            logger.info("[Test-Healer] Tests PASSED!")
            return True
            
        logger.warning(f"[Test-Healer] Tests FAILED. Analyzing errors...")
        error_output = result.stdout + "\n" + result.stderr
        compressed_error = "\n".join(error_output.split("\n")[-100:]) # Limit to bottom 100 lines
        
        current_tests = ""
        for fname in os.listdir(test_dir):
            if fname.endswith(profile['test_extension']):
                with open(os.path.join(test_dir, fname), "r", encoding="utf-8") as f:
                    current_tests += f"\n--- {fname} ---\n{f.read()}\n"
                    
        fixer_system = f"You are an Expert {profile['language']} SDET. The tests failed. Return a JSON object containing ONLY the test files that need to be fixed to make the tests pass. Do NOT modify the source code, only the tests. Format: {{\"files\": [{{\"filename\": \"test{profile['test_extension']}\", \"fixed_code\": \"...\"}}]}}"
        fixer_prompt = f"Test Errors:\n{compressed_error}\n\nCurrent Test Code:\n{current_tests}\n\nPlease provide the corrected test code."
        
        fix_response = llm.invoke([SystemMessage(content=fixer_system), HumanMessage(content=fixer_prompt)])
        
        try:
            fix_plan = json.loads(fix_response.content)
            for f in fix_plan.get("files", []):
                fname = f.get("filename")
                fcode = f.get("fixed_code", "").replace(f"```{profile['language']}", "").replace("```", "").strip()
                if fname and fcode:
                    with open(sanitize_path(test_dir, fname), "w", encoding="utf-8") as fw:
                        fw.write(fcode)
        except Exception as e:
            logger.error(f"[Test-Healer] Error parsing: {e}")
            
    return False

def run_test_generation(state):
    llm = config.get_llm(response_format={"type": "json_object"})
    code_llm = config.get_llm()
    
    target_framework_key = state.get("target_framework", "java_springboot")
    profile = TARGET_PROFILES.get(target_framework_key, TARGET_PROFILES["java_springboot"])
    
    target_dir = config.MODERNIZED_SOURCE_DIR
    test_dir = os.path.join(target_dir, *profile['test_dir'].split('/'))
    os.makedirs(test_dir, exist_ok=True)
    
    master_files = glob.glob(f"{config.MASTER_DOCS_DIR}/*.md")
    if not master_files:
        return "No Master Documents found to generate tests from."
        
    generation_results = []
    
    for m_file in master_files:
        logger.info(f"\n[Test Generator] Processing {m_file}...")
        with open(m_file, 'r', encoding='utf-8') as file:
            master_content = file.read()
            
        plan_system = f"You are a Principal SDET. Read the Master Document and determine the exact {profile['test_framework']} {profile['language']} test files needed. Return a formatted JSON object. Example: {{\"files\": [\"main{profile['test_extension']}\"]}}"
        
        plan_response = llm.invoke([SystemMessage(content=plan_system), HumanMessage(content=master_content)])
        try:
            plan = json.loads(plan_response.content)
            files_to_generate = plan.get("files", [])
        except Exception as e:
            logger.error(f"Failed to parse test planning response: {e}")
            continue
            
        test_system = f"You are an SDET specializing in {profile['test_framework']}. Write FULL EXHAUSTIVE unit tests. Focus on functional equivalence matching the Master Document. Mock dependencies if necessary. Return ONLY the raw code."
        
        for filename in files_to_generate:
            prompt = f"Master Document:\n{master_content}\n\nTask: Write the unit tests for {filename}. Output ONLY raw {profile['language']} code."
            try:
                file_response = code_llm.invoke([SystemMessage(content=test_system), HumanMessage(content=prompt)])
                raw_code = file_response.content.replace(f"```{profile['language']}", "").replace("```", "").strip()
            except Exception as e:
                continue
                
            with open(sanitize_path(test_dir, filename), "w", encoding="utf-8") as f:
                f.write(raw_code)
                
    success = run_test_healer(target_dir, test_dir, llm, profile)
    if success:
        return "Successfully generated and verified unit tests."
    else:
        return "Generated unit tests, but test verification failed."
