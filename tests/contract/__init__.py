````

---

## CI Config — Import Linter

````ini
<vscode_codeblock_uri>file:///c%3A/Users/INTEL/OneDrive/Documents/GitHub/TUYUL-FX-WOLF-15LAYER-SYSTEM/.importlinter</vscode_codeblock_uri>[importlinter]
root_package = .

[importlinter:contract:no-reverse-deps]
name = Dashboard must not be imported by engines or analysis
type = forbidden
source_modules =
    engines
    analysis
    constitution
forbidden_modules =
    dashboard