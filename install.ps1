# Instalador de vpn9ne para Windows (PowerShell como Administrador)
winget install -e --id OpenVPN.OpenVPN
winget install -e --id Python.Python.3.12
python -m pip install --user pipx
python -m pipx ensurepath
python -m pipx install --force git+https://github.com/sam9neREYES/vpn9ne.git
Write-Host "Listo. Abre una terminal NUEVA como Administrador y ejecuta: vpn9ne"
