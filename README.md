# vpn9ne

VPN de terminal para Linux, macOS y Windows. Motor: OpenVPN. Mientras el
programa corre en la terminal, la VPN esta activa; Ctrl+C o cerrar la
terminal la apaga.

## Instalacion rapida

**Linux / macOS**
```
curl -fsSL https://raw.githubusercontent.com/sam9neREYES/vpn9ne/main/install.sh | sh
```

**Windows (PowerShell como Administrador)**
```
irm https://raw.githubusercontent.com/sam9neREYES/vpn9ne/main/install.ps1 | iex
```

**Manual** (con OpenVPN y pipx ya instalados)
```
pipx install git+https://github.com/sam9neREYES/vpn9ne.git
```

## Uso
```
vpn9ne                 # menu interactivo
vpn9ne connect JP      # conectar directo (US, JP, RU, KR, ...)
vpn9ne list            # paises disponibles
vpn9ne refresh         # actualizar servidores
vpn9ne doctor          # revisar requisitos
```
En Windows ejecuta la terminal como Administrador. En Linux/macOS el programa pide sudo solo.

## Servidores propios
Coloca tus archivos `.ovpn` en `~/.vpn9ne/configs/US/`, `.../JP/`, etc.
Tienen prioridad sobre los publicos.

## Desinstalar
```
pipx uninstall vpn9ne
```
