# Build PDF-AI-Assistant.exe on Windows. Run from the project folder.
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm PDF-AI-Assistant.spec
Write-Host "Built dist\PDF-AI-Assistant.exe"
