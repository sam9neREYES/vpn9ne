#!/usr/bin/env sh
# Instalador de vpn9ne para Linux y macOS
set -e
echo "==> Instalando dependencias (OpenVPN, Python, pipx)..."
if [ "$(uname)" = "Darwin" ]; then
  command -v brew >/dev/null || { echo "Instala Homebrew primero: https://brew.sh"; exit 1; }
  brew install openvpn python pipx
elif command -v apt >/dev/null; then
  sudo apt update && sudo apt install -y openvpn python3 pipx
elif command -v dnf >/dev/null; then
  sudo dnf install -y openvpn python3 pipx
elif command -v pacman >/dev/null; then
  sudo pacman -S --noconfirm openvpn python python-pipx
else
  echo "Distro no reconocida: instala openvpn, python3 y pipx manualmente."; exit 1
fi
pipx ensurepath
echo "==> Instalando vpn9ne desde GitHub..."
pipx install --force git+https://github.com/sam9neREYES/vpn9ne.git
echo "Listo. Abre una terminal nueva y ejecuta: vpn9ne"
