import os
import glob
import json
import requests
import zipfile
import subprocess
import platform
from langchain_core.messages import HumanMessage, SystemMessage
import config
from utils import setup_logger, sanitize_path

logger = setup_logger("CodeGenerator")

from utils.language_profiles import TARGET_PROFILES

def init_target_project(target_dir, profile):
    """Initializes the target project based on the profile."""
    logger.info(f"Initializing {profile['framework']} project in {target_dir}...")
    
    if profile['language'] == 'java' and profile['build_tool'] == 'maven':
        # Fallback to Spring Initializr for Java
        url = "https://start.spring.io/starter.zip"
        params = {
            "type": "maven-project", "language": "java", "baseDir": "",
            "groupId": "com.example", "artifactId": "demo", "name": "demo",
            "packageName": "com.example.demo", "packaging": "jar",
            "javaVersion": "21", "dependencies": "web,lombok"
        }
        response = requests.get(url, params=params)
        if response.status_code == 200:
            zip_path = os.path.join(target_dir, "demo.zip")
            os.makedirs(target_dir, exist_ok=True)
            with open(zip_path, "wb") as f:
                f.write(response.content)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(target_dir)
            os.remove(zip_path)
            logger.info("Java project initialized successfully.")
    else:
        # Generic folder creation for Python/JS
        src_path = os.path.join(target_dir, profile['src_dir'])
        test_path = os.path.join(target_dir, profile['test_dir'])
        os.makedirs(src_path, exist_ok=True)
        os.makedirs(test_path, exist_ok=True)
        logger.info(f"{profile['framework']} generic project initialized.")

def run_auto_healer(target_dir, src_dir, llm, profile, phase_name=""):
    """Generic auto-healer based on build tool."""
    if profile['build_tool'] != 'maven':
        logger.warning(f"[Auto-Healer] Auto-healing compilation not supported yet for {profile['build_tool']}. Skipping.")
        return True # Skip healing for now
        
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        logger.info(f"\n[Auto-Healer {phase_name}] Attempt {attempt}: Compiling project...")
        is_windows = platform.system() == "Windows"
        mvn_cmd = "mvnw.cmd" if is_windows else "./mvnw"
        if not is_windows:
            subprocess.run(["chmod", "+x", "mvnw"], cwd=target_dir)
            
        try:
            result = subprocess.run([mvn_cmd, "clean", "compile"], cwd=target_dir, capture_output=True, text=True, shell=is_windows, timeout=300)
        except subprocess.TimeoutExpired:
            return False
            
        if result.returncode == 0:
            return True
            
        logger.warning(f"[Auto-Healer {phase_name}] Build FAILED. Analyzing compiler errors...")
        error_output = result.stdout + "\n" + result.stderr
        error_lines = [line for line in error_output.split("\n") if "[ERROR]" in line]
        compressed_error = "\n".join(error_lines[:50])
        
        current_files = ""
        for fname in os.listdir(src_dir):
            if fname.endswith(profile['extension']):
                with open(os.path.join(src_dir, fname), "r", encoding="utf-8") as f:
                    current_files += f"\n--- {fname} ---\n{f.read()}\n"
        
        fixer_system = f"You are an Expert {profile['language']} Debugger. Return a JSON object containing ONLY the files that need to be fixed, with their full corrected code. Format: {{\"files\": [{{\"filename\": \"file{profile['extension']}\", \"fixed_code\": \"...\"}}]}}"
        fixer_prompt = f"Errors:\n{compressed_error}\n\nCurrent Source Code:\n{current_files}\n\nPlease provide the fully corrected code."
        
        fix_response = llm.invoke([SystemMessage(content=fixer_system), HumanMessage(content=fixer_prompt)])
        
        try:
            fix_plan = json.loads(fix_response.content)
            for f in fix_plan.get("files", []):
                fname = f.get("filename")
                fcode = f.get("fixed_code", "").replace(f"```{profile['language']}", "").replace("```", "").strip()
                if fname and fcode:
                    with open(sanitize_path(src_dir, fname), "w", encoding="utf-8") as fw:
                        fw.write(fcode)
        except Exception as e:
            logger.error(f"[Auto-Healer] Error parsing: {e}")
            
    return False

def run_code_generation(state):
    """Runs the modular code generation loop dynamically."""
    llm = config.get_llm(response_format={"type": "json_object"})
    code_llm = config.get_llm()
    
    target_framework_key = state.get("target_framework", "java_springboot")
    profile = TARGET_PROFILES.get(target_framework_key, TARGET_PROFILES["java_springboot"])
    
    master_files = glob.glob(f"{config.MASTER_DOCS_DIR}/*.md")
    if not master_files:
        return "No Master Documents found to generate code from."
        
    target_dir = config.MODERNIZED_SOURCE_DIR
    init_target_project(target_dir, profile)
    
    src_dir = os.path.join(target_dir, *profile['src_dir'].split('/'))
    os.makedirs(src_dir, exist_ok=True)
    
    generation_results = []
    
    for m_file in master_files:
        logger.info(f"\n[Code Generator] Processing {m_file}...")
        with open(m_file, 'r', encoding='utf-8') as file:
            master_content = file.read()
            
        logger.info("[Phase 1] Planning architecture...")
        plan_system = f"You are a Principal Software Architect. Read the Master Document and determine the exact {profile['framework']} {profile['language']} files needed. Return a strictly formatted JSON object with a single key 'files' containing a list of strings representing the filenames. Example: {{\"files\": [\"main{profile['extension']}\"]}}"
        
        plan_response = llm.invoke([SystemMessage(content=plan_system), HumanMessage(content=master_content)])
        try:
            plan = json.loads(plan_response.content)
            files_to_generate = plan.get("files", [])
        except Exception as e:
            raise Exception(f"Failed to parse planning response: {e}")
            
        skeleton_system = f"You are a Senior Developer specializing in {profile['framework']} and {profile['language']}. Write ONLY the SKELETON for the requested file. Include package/imports, class definitions, and method signatures. DO NOT WRITE BUSINESS LOGIC. Leave all methods empty. Return ONLY the raw code."
        
        for filename in files_to_generate:
            prompt = f"Master Document:\n\n{master_content}\n\nTask: Write the SKELETON code for {filename}. Output ONLY raw {profile['language']} code."
            try:
                file_response = code_llm.invoke([SystemMessage(content=skeleton_system), HumanMessage(content=prompt)])
                raw_code = file_response.content.replace(f"```{profile['language']}", "").replace("```", "").strip()
            except Exception as e:
                raw_code = f"// Skeleton generation failed"
            
            with open(sanitize_path(src_dir, filename), "w", encoding="utf-8") as f:
                f.write(raw_code)
                
        run_auto_healer(target_dir, src_dir, llm, profile, phase_name="Skeleton")
        
        healed_skeletons = ""
        for filename in files_to_generate:
            file_path = sanitize_path(src_dir, filename)
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    healed_skeletons += f"--- {filename} ---\n{f.read()}\n\n"

        logic_system = f"You are a Senior Developer specializing in {profile['framework']} and {profile['language']}. Fill in the business logic. You have the complete compiling SKELETON project context. Write the FULL and EXHAUSTIVE complete code for the file. Return ONLY the raw code."
        
        for filename in files_to_generate:
            prompt = f"Master Document:\n{master_content}\n\nAll Healed Skeletons Context:\n{healed_skeletons}\n\nTask: Write the FULL IMPLEMENTED code for {filename} by filling in the skeleton. Output ONLY raw {profile['language']} code."
            try:
                file_response = code_llm.invoke([SystemMessage(content=logic_system), HumanMessage(content=prompt)])
                raw_code = file_response.content.replace(f"```{profile['language']}", "").replace("```", "").strip()
            except Exception as e:
                continue
                
            with open(sanitize_path(src_dir, filename), "w", encoding="utf-8") as f:
                f.write(raw_code)
                
        success = run_auto_healer(target_dir, src_dir, llm, profile, phase_name="Implementation")
        if success:
            generation_results.append(f"Successfully generated code for {m_file}")
        else:
            generation_results.append(f"Finished code generation for {m_file}, but compiling failed.")
            
    return "\n".join(generation_results)
