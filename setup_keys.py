#!/usr/bin/env python3
"""Helper script to generate Ed25519 keys and set up config."""

import json
import shutil
from pathlib import Path

from bot.auth import generate_keypair


def main():
    print("\n🔐 Revolut X - Configuración de claves API\n")
    print("=" * 50)

    if Path("private.pem").exists():
        resp = input("Ya existe private.pem. ¿Regenerar? (s/N): ")
        if resp.lower() != "s":
            print("Usando claves existentes.")
        else:
            public_key = generate_keypair()
            print(f"\n✅ Claves regeneradas.\n\nClave pública:\n{public_key}")
    else:
        public_key = generate_keypair()
        print(f"\n✅ Claves generadas.\n\nClave pública (pega esto en Revolut X):\n{public_key}")

    if not Path("config.json").exists():
        shutil.copy("config.example.json", "config.json")
        print("\n📝 config.json creado desde config.example.json")

    print("\n📋 Pasos:")
    print("1. Ve a Revolut X → Configuración → API → Crear clave API")
    print("2. Pega la clave pública de arriba")
    print("3. Marca: ✅ Vista de órdenes al contado")
    print("4. Marca: ✅ Operaciones al contado")
    print("5. Copia el 'Nombre de la clave API' (API Key)")
    api_key = input("\n¿Tienes el API Key? Pégalo aquí (o Enter para después): ").strip()

    if api_key:
        config = json.loads(Path("config.json").read_text())
        config["api_key"] = api_key
        Path("config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False))
        print("✅ API Key guardado en config.json")

    print("\n🚀 Para iniciar el bot:")
    print("   python -m bot run          # Trading + dashboard")
    print("   python -m bot dashboard    # Solo dashboard")
    print("   python -m bot status       # Ver estado")
    print("\n⚠️  El bot arranca en modo DRY RUN (simulación).")
    print("   Cambia dry_run a false en config.json para operar en real.\n")


if __name__ == "__main__":
    main()
