import os
import tokenize

def check_indentation(file_path):
    try:
        with tokenize.open(file_path) as f:
            first_indent_type = None
            for token in tokenize.generate_tokens(f.readline):
                if token.type == tokenize.INDENT:
                    if first_indent_type is None:
                        # Found first indentation, remember if it's spaces or tabs
                        first_indent_type = 'spaces' if token.string.startswith(' ') else 'tabs'
                    else:
                        # Compare with first indentation type
                        current_type = 'spaces' if token.string.startswith(' ') else 'tabs'
                        if current_type != first_indent_type:
                            print(f"Mixed indentation in {file_path} at line {token.start[0]}")
                            print(f"First indent type: {first_indent_type}")
                            print(f"Current indent type: {current_type}")
                            return False
    except Exception as e:
        print(f"Error processing {file_path}: {str(e)}")
        return False
    return True

def check_directory(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                print(f"\nChecking {file_path}...")
                check_indentation(file_path)

# Usage
check_directory('app')