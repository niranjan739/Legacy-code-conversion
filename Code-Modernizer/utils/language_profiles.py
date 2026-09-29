SOURCE_PROFILES = {
    "java": {
        "extension": ".java",
        "splitter_language": "java",
        "description": "Legacy Java Application"
    },
    "cobol": {
        "extension": ".cbl", # or .cob
        "splitter_language": "cobol", # Note: Tree-sitter doesn't have an official cobol parser by default, might need fallback
        "description": "Legacy COBOL Application"
    },
    "python": {
        "extension": ".py",
        "splitter_language": "python",
        "description": "Legacy Python Scripting"
    }
}

TARGET_PROFILES = {
    "java_springboot": {
        "language": "java",
        "framework": "Spring Boot",
        "extension": ".java",
        "test_extension": ".java",
        "test_framework": "JUnit 5",
        "build_tool": "maven",
        "src_dir": "src/main/java/com/example/demo",
        "test_dir": "src/test/java/com/example/demo"
    },
    "python_fastapi": {
        "language": "python",
        "framework": "FastAPI",
        "extension": ".py",
        "test_extension": "_test.py",
        "test_framework": "pytest",
        "build_tool": "pip",
        "src_dir": "app",
        "test_dir": "tests"
    },
    "javascript_express": {
        "language": "javascript",
        "framework": "Express",
        "extension": ".js",
        "test_extension": ".test.js",
        "test_framework": "jest",
        "build_tool": "npm",
        "src_dir": "src",
        "test_dir": "tests"
    }
}
