import os
import tempfile
import patoolib
import pandas as pd
from kopyt import Parser, node
import re 

def manual_max_nesting(code):
    indent_stack = []
    max_depth = 0
    for line in code.split("\n"):
        line = line.strip()
        if line.startswith(("if", "for", "while", "catch", "when", "try", "else")):
            indent_stack.append(line)
            max_depth = max(max_depth, len(indent_stack))
        elif line == "}":
            if indent_stack:
                indent_stack.pop()
    return max_depth

def count_cc_manual(code):
    cc = 1
    control_keywords = ["if", "for", "while", "when", "catch", "case"]
    for line in code.split("\n"):
        line = line.strip()
        for kw in control_keywords:
            if line.startswith(kw):
                cc += 1
    return cc

def count_woc(cc_values):
    total = sum(cc_values)
    return [cc / total if total > 0 else 0 for cc in cc_values]

def count_mamcl(code):
    max_chain = 0
    lines = code.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith(("//", "/*", "*", "*/")):
            continue
            
        # Cari semua chain method calls dalam satu baris
        current_chain = 0
        parts = line.split(".")
        if len(parts) > 1:
            # Mulai dari index 1 karena index 0 adalah objek
            for part in parts[1:]:
                # Check if it's a method call (contains parentheses)
                if "(" in part and ")" in part:
                    current_chain += 1
                else:
                    # Reset if not a method call, as the chain is broken
                    current_chain = 0
                    break # Stop processing this line as chain is broken
        max_chain = max(max_chain, current_chain)
    return max_chain

def count_noav_method(method_code):
    # Hitung jumlah atribut unik yang diakses melalui this.[property] (termasuk this?. dan this!!.)
    attributes = set()
    # Regex: cari this(.|?.|!!.)propertyName yang tidak diikuti '('
    # Lebih toleran terhadap spasi dan variasi penulisan
    pattern = re.compile(
        r'\bthis\s*([\?\!]*\s*\.\s*)\s*([a-zA-Z_][a-zA-Z0-9_]*)\b(?!\s*\()'
    )
    for line in method_code.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "/*", "*", "*/")):
            continue
        if stripped.startswith(("class ", "fun ", "interface ", "package ", "import ", "var ", "val ")):
            continue
        for match in pattern.finditer(stripped):
            attributes.add(match.group(2))
    return len(attributes)

def count_cm_method(method_code, all_methods_in_file):
    """Count Coupling between Methods (CM)"""
    count = 0
    method_lines = method_code.splitlines()
    
    for method_name in all_methods_in_file:
        # We need to make sure we are looking for actual calls, not just substrings
        # and not the method itself if it's currently being analyzed.
        # This is a heuristic. A full AST-based approach would be more robust.
        
        # Avoid counting the method itself as coupling with itself
        # This check is heuristic and might miss cases.
        # Example: if method 'foo' calls 'this.foo()', it would still be counted by simple string match.
        # For simplicity, we assume 'method_name' is usually unique enough here.
        
        for line in method_lines:
            line = line.strip()
            if not line or line.startswith(("//", "/*", "*", "*/")):
                continue
                
            # A more robust check for method calls.
            # Look for "methodName(" or "methodName ("
            # This avoids matching if "methodName" is just part of a variable name.
            if re.search(r'\b' + re.escape(method_name) + r'\s*\(', line):
                count += 1
                break  # Count once per distinct method called within the current method
    return count


def count_loc_type(class_code):
    return class_code.count("\n") + 1


def count_noav_class(class_decl):
    count = 0
    # Ensure class_decl.body and class_decl.body.members exist
    if hasattr(class_decl, 'body') and class_decl.body and hasattr(class_decl.body, 'members'):
        for member in class_decl.body.members:
            # Only count property/variable declarations at the class level
            if hasattr(node, 'PropertyDeclaration') and isinstance(member, node.PropertyDeclaration):
                count += 1  # Increment for each class-level property
            # Also check for VariableDeclaration, but typically not used for class-level in Kopyt
            elif hasattr(node, 'VariableDeclaration') and isinstance(member, node.VariableDeclaration):
                # Not incrementing count here, as class-level variables are usually PropertyDeclaration
                pass 
    return count  # Total number of class-level attributes (properties/fields)

def count_locnamm_type(class_decl):
    count = 0
    if hasattr(class_decl, 'body') and class_decl.body and hasattr(class_decl.body, 'members'):
        for member in class_decl.body.members:
            if isinstance(member, node.FunctionDeclaration):
                # Check if it's a non-accessor method
                if not member.name.startswith(("get", "set", "is")):
                    count += str(member.body).count("\n") + 1 if member.body else 0
    return count

def count_cfnamm_type(class_decl):
    methods = []
    if hasattr(class_decl, 'body') and class_decl.body and hasattr(class_decl.body, 'members'):
        for m in class_decl.body.members:
            if isinstance(m, node.FunctionDeclaration) and not m.name.startswith(("get", "set", "is")):
                methods.append(m.name)
    coupled = 0
    if hasattr(class_decl, 'body') and class_decl.body and hasattr(class_decl.body, 'members'):
        for m in class_decl.body.members:
            if isinstance(m, node.FunctionDeclaration) and m.name in methods:
                body = str(m.body)
                # Check for calls to other non-accessor methods within the same class
                if any(other_method_name != m.name and re.search(r'\b' + re.escape(other_method_name) + r'\s*\(', body) for other_method_name in methods):
                    coupled += 1
    return coupled / len(methods) if methods else 0

def extracted_method(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()
        parser = Parser(code)
        result = parser.parse()

        # Extract package name from AST or fallback to 'UNKNOWN'
        if hasattr(result, 'package') and result.package:
            package_name = result.package.name if hasattr(result.package, 'name') else str(result.package)
        else:
            package_name = "UNKNOWN"
        # --- PACKAGE-LEVEL METRICS ---
        declarations = result.declarations if hasattr(result, 'declarations') else []
        class_decls = [n for n in declarations if isinstance(n, node.ClassDeclaration)]
        interface_decls = [n for n in declarations if isinstance(n, node.InterfaceDeclaration)]
        function_decls = [n for n in declarations if isinstance(n, node.FunctionDeclaration)]

        # --- PACKAGE-LEVEL METRICS ---
        nomnamm_package = sum(1 for f in function_decls if not f.name.startswith(("get", "set", "is")))
        for c in class_decls:
            if hasattr(c, 'body') and c.body and hasattr(c.body, 'members'):
                for m in c.body.members:
                    if isinstance(m, node.FunctionDeclaration) and not m.name.startswith(("get", "set", "is")):
                        nomnamm_package += 1
        noi_package = len(interface_decls)
        loc_package = code.count("\n") + 1

        # Simpan metrik package-level dalam dictionary berdasarkan package_name
        package_metrics_map = {
            package_name: {
                'NOMNAMM_Package': nomnamm_package,
                'NOI_Package': noi_package,
                'LOC_Package': loc_package
            }
        }

        # Kumpulkan semua nama method di file untuk CM calculation
        all_methods_in_file = [f.name for f in function_decls if not f.name.startswith(("get", "set", "is"))]
        for c in class_decls:
            if hasattr(c, 'body') and c.body and hasattr(c.body, 'members'):
                for m in c.body.members:
                    if isinstance(m, node.FunctionDeclaration) and not m.name.startswith(("get", "set", "is")):
                        all_methods_in_file.append(m.name)

        datas = []

        for class_decl in class_decls:
            if not class_decl.body:
                continue

            class_name = class_decl.name
            loc_type = count_loc_type(str(class_decl))
            locnamm_type = count_locnamm_type(class_decl)
            cfnamm_type = count_cfnamm_type(class_decl)

            noav_class_val = count_noav_class(class_decl)

            methods_data = {}
            for member in class_decl.body.members:
                if isinstance(member, node.FunctionDeclaration):
                    name = member.name
                    body = str(member.body) if member.body else ""

                    cc = count_cc_manual(body)
                    loc = body.count("\n") + 1 if body else 0
                    max_nest = manual_max_nesting(body)
                    mamcl = count_mamcl(body)
                    cm = count_cm_method(body, all_methods_in_file)
                    noav_method_val = count_noav_method(body) 

                    methods_data[name] = (cc, loc, max_nest, mamcl, noav_method_val, cm)

            woc_values = count_woc([cc for cc, *_ in methods_data.values()])

            # Ambil metrik package-level dari dictionary
            pkg_metrics = package_metrics_map.get(package_name, {'NOMNAMM_Package': 0, 'NOI_Package': 0, 'LOC_Package': 0})

            # Ensure woc_values aligns with methods_data if some methods have 0 CC
            # Use enumerate to keep track of index for woc_values
            for i, (name, (cc, loc, nest, mamcl, noav_method_val, cm)) in enumerate(methods_data.items()):
                woc = woc_values[i] if i < len(woc_values) else 0 # Fallback if woc_values is shorter for some reason
                datas.append({
                    "Package": package_name,
                    "Class": class_name,
                    "Method": name,
                    "LOC": loc,
                    "Max Nesting": nest,
                    "CC": cc,
                    "WOC": woc,
                    "MaMCL": mamcl,
                    "NOAV": noav_method_val, 
                    "CM": cm,
                    "LOC_type": loc_type,
                    "LOCNAMM_type": locnamm_type,
                    "CFNAMM_type": cfnamm_type,
                    "NOMNAMM_Package": pkg_metrics['NOMNAMM_Package'],
                    "NOI_Package": pkg_metrics['NOI_Package'],
                    "LOC_package": pkg_metrics['LOC_Package']
                })

        # Tambahkan fungsi top-level ke dalam hasil
        pkg_metrics = package_metrics_map.get(package_name, {'NOMNAMM_Package': 0, 'NOI_Package': 0, 'LOC_Package': 0})
        for func in function_decls:
            body = str(func.body) if func.body else ""
            cc = count_cc_manual(body)
            loc = body.count("\n") + 1 if body else 0
            max_nest = manual_max_nesting(body)
            mamcl = count_mamcl(body)
            noav_method_val = count_noav_method(body) 
            cm = count_cm_method(body, all_methods_in_file)
            
            datas.append({
                "Package": package_name,
                "Class": "TopLevel",
                "Method": func.name,
                "LOC": loc,
                "Max Nesting": max_nest,
                "CC": cc,
                "WOC": 1 if cc > 0 else 0, # WOC for top-level function is 1 if it has CC
                "MaMCL": mamcl,
                "NOAV": noav_method_val, 
                "CM": cm,
                "LOC_type": 0, # Not applicable for top-level functions
                "LOCNAMM_type": 0, # Not applicable for top-level functions
                "CFNAMM_type": 0, # Not applicable for top-level functions
                "NOMNAMM_Package": pkg_metrics['NOMNAMM_Package'],
                "NOI_Package": pkg_metrics['NOI_Package'],
                "LOC_package": pkg_metrics['LOC_Package']
            })

        return datas if datas else [{
            "Package": package_name, "Class": "None", "Method": "None",
            "LOC": 0, "Max Nesting": 0, "CC": 0, "WOC": 0,
            "MaMCL": 0, "NOAV": 0, "CM": 0,
            "LOC_type": 0, "LOCNAMM_type": 0, "CFNAMM_type": 0,
            "NOMNAMM_Package": nomnamm_package, "NOI_Package": noi_package, 
            "LOC_package": loc_package, "Error": "No functions found"
        }]
    except Exception as e:
        return [{
            "Package": "Error", "Class": "Error", "Method": "Error",
            "LOC": "Error", "Max Nesting": 0, "CC": 0, "WOC": 0,
            "MaMCL": 0, "NOAV": 0, "CM": 0,
            "LOC_type": 0, "LOCNAMM_type": 0, "CFNAMM_type": 0,
            "NOMNAMM_Package": 0, "NOI_Package": 0, "LOC_package": 0, 
            "Error": str(e)
        }]


def extract_and_parse(file):
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_file_path = os.path.join(temp_dir, file.name)
        try:
            # Tulis file ke temporary directory
            with open(temp_file_path, "wb") as f:
                f.write(file.getbuffer())

            # Ekstrak arsip
            patoolib.extract_archive(temp_file_path, outdir=temp_dir)
            
            # Cari semua file Kotlin
            kotlin_files = [
                os.path.join(root, f)
                for root, _, files in os.walk(temp_dir)
                for f in files if f.endswith(".kt") or f.endswith(".kts")
            ]

            if not kotlin_files:
                return pd.DataFrame([{
                    "Package": "Error",
                    "Class": "Error",
                    "Method": "Error",
                    "LOC": "Error",
                    "Max Nesting": 0,
                    "CC": 0,
                    "WOC": 0,
                    "MaMCL": 0,
                    "NOAV": 0,
                    "CM": 0,
                    "LOC_type": 0,
                    "LOCNAMM_type": 0,
                    "CFNAMM_type": 0,
                    "NOMNAMM_Package": 0,
                    "NOI_Package": 0,
                    "LOC_package": 0,
                    "Error": "No Kotlin files found in archive"
                }])

            results = []
            file_package_map = {}  # file_path -> package_name
            file_code_map = {}     # file_path -> code string

            # Pass 1: Kumpulkan hasil per file dan mapping file ke package
            for kotlin_file in kotlin_files:
                try:
                    with open(kotlin_file, "r", encoding="utf-8") as f:
                        code = f.read()
                    parser = Parser(code)
                    result = parser.parse()
                    if hasattr(result, 'package') and result.package:
                        package_name = result.package.name if hasattr(result.package, 'name') else str(result.package)
                    else:
                        package_name = "UNKNOWN"
                    file_package_map[kotlin_file] = package_name
                    file_code_map[kotlin_file] = code
                    file_result = extracted_method(kotlin_file)
                    if file_result:
                        results.extend(file_result)
                except Exception as file_error:
                    results.append({
                        "Package": "Error",
                        "Class": "Error",
                        "Method": kotlin_file,
                        "LOC": "Error",
                        "Max Nesting": 0,
                        "CC": 0,
                        "WOC": 0,
                        "MaMCL": 0,
                        "NOAV": 0,
                        "CM": 0,
                        "LOC_type": 0,
                        "LOCNAMM_type": 0,
                        "CFNAMM_type": 0,
                        "NOMNAMM_Package": 0,
                        "NOI_Package": 0,
                        "LOC_package": 0,
                        "Error": str(file_error)
                    })

            # Pass 2: Hitung ulang metrik package-level secara agregat
            # Kumpulkan semua file per package
            package_files = {}
            for file_path, pkg in file_package_map.items():
                package_files.setdefault(pkg, []).append(file_path)

            # Hitung metrik package-level agregat
            package_metrics_map = {}
            for pkg, files in package_files.items():
                all_code = ""
                all_functions = 0
                all_interfaces = 0
                for file_path in files:
                    code = file_code_map[file_path]
                    all_code += code + "\n"
                    parser = Parser(code)
                    result = parser.parse()
                    declarations = result.declarations if hasattr(result, 'declarations') else []
                    class_decls = [n for n in declarations if isinstance(n, node.ClassDeclaration)]
                    interface_decls = [n for n in declarations if isinstance(n, node.InterfaceDeclaration)]
                    function_decls = [n for n in declarations if isinstance(n, node.FunctionDeclaration)]
                    all_functions += sum(1 for f in function_decls if not f.name.startswith(("get", "set", "is")))
                    for c in class_decls:
                        if hasattr(c, 'body') and c.body and hasattr(c.body, 'members'):
                            for m in c.body.members:
                                if isinstance(m, node.FunctionDeclaration) and not m.name.startswith(("get", "set", "is")):
                                    all_functions += 1
                    all_interfaces += len(interface_decls)
                loc_package = all_code.count("\n") + 1
                package_metrics_map[pkg] = {
                    'NOMNAMM_Package': all_functions,
                    'NOI_Package': all_interfaces,
                    'LOC_Package': loc_package
                }

            # Update semua baris di results dengan metrik package-level agregat
            for row in results:
                pkg = row.get("Package", "UNKNOWN")
                pkg_metrics = package_metrics_map.get(pkg, {'NOMNAMM_Package': 0, 'NOI_Package': 0, 'LOC_Package': 0})
                row["NOMNAMM_Package"] = pkg_metrics['NOMNAMM_Package']
                row["NOI_Package"] = pkg_metrics['NOI_Package']
                row["LOC_package"] = pkg_metrics['LOC_Package']

            df = pd.DataFrame(results)
            
            # Tambahkan baris total
            numeric_columns = ['LOC', 'Max Nesting', 'CC', 'WOC', 'MaMCL', 'NOAV', 'CM', 
                                'LOC_type', 'LOCNAMM_type', 'CFNAMM_type', 'NOMNAMM_Package', 
                                'NOI_Package', 'LOC_package']
            
            # Konversi kolom 'LOC' ke numerik, ganti 'Error' dengan 0
            df['LOC'] = pd.to_numeric(df['LOC'].replace('Error', 0))
            
            # Hitung total
            totals = df[numeric_columns].sum()
            
            # Buat baris total
            total_row = pd.DataFrame([{
                'Package': 'TOTAL',
                'Class': '',
                'Method': '',
                **totals,
                'Error': ''
            }])
            
            # Gabungkan DataFrame asli dengan baris total
            df = pd.concat([df, total_row], ignore_index=True)
            
            return df

        except Exception as e:
            return pd.DataFrame([{
                "Package": "Error",
                "Class": "Error",
                "Method": "Error",
                "LOC": "Error",
                "Max Nesting": 0,
                "CC": 0,
                "WOC": 0,
                "MaMCL": 0,
                "NOAV": 0,
                "CM": 0,
                "LOC_type": 0,
                "LOCNAMM_type": 0,
                "CFNAMM_type": 0,
                "NOMNAMM_Package": 0,
                "NOI_Package": 0,
                "LOC_package": 0,
                "Error": f"Archive extraction error: {str(e)}"
            }])