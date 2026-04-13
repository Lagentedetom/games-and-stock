# Games & Stock Dashboard

Dashboard bilingue (ES/EN) que analiza la correlacion entre lanzamientos de videojuegos AAA y movimientos bursatiles.

## Estructura

```
web/
├── index.html                    # Dashboard en Espanol
├── en/
│   └── index.html                # Dashboard en Ingles
├── data/
│   └── games_data.json           # Datos estructurados
├── scripts/
│   ├── update_data.py            # Actualiza precios desde Yahoo Finance
│   └── generate_html.py          # Regenera HTMLs con datos frescos
├── .github/
│   └── workflows/
│       └── update-dashboard.yml  # GitHub Action: actualizacion diaria
└── README.md
```

## Deploy en GitHub Pages

1. Crear repo en GitHub: `games-and-stock` (o el nombre que prefieras)
2. Subir el contenido de la carpeta `web/` como raiz del repo:
   ```bash
   cd web
   git init
   git add -A
   git commit -m "Initial commit: Games & Stock Dashboard"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/games-and-stock.git
   git push -u origin main
   ```
3. En GitHub → Settings → Pages → Source: "GitHub Actions"
4. El dashboard estara en: `https://TU_USUARIO.github.io/games-and-stock/`

## Actualizacion automatica

El GitHub Action `update-dashboard.yml` se ejecuta diariamente a las 09:00 CET:
1. Descarga precios actualizados via Yahoo Finance
2. Actualiza `games_data.json`
3. Regenera fechas y precios en ambos HTMLs
4. Hace commit y deploy automatico

Para ejecutar manualmente: Actions → "Update Dashboard Daily" → "Run workflow"

## Ejecucion local

```bash
pip install yfinance requests
python scripts/update_data.py      # Actualiza precios
python scripts/generate_html.py    # Regenera HTMLs
```

## Dominio personalizado (opcional)

1. Comprar dominio (ej: gamesandstock.com ~$10/ano)
2. En GitHub Pages Settings → Custom domain: `gamesandstock.com`
3. Crear archivo `CNAME` en raiz del repo con: `gamesandstock.com`
4. Configurar DNS: CNAME apuntando a `TU_USUARIO.github.io`
