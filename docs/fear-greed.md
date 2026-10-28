# Bitcoin Fear & Greed histórico

`tradingagents.dataflows.vendors.fear_greed` consulta el índice gratuito de
[Alternative.me](https://alternative.me/crypto/fear-and-greed-index/). Su API
permite consultar el histórico sin clave y exige atribución junto al dato.

```python
from tradingagents.dataflows.vendors.fear_greed import (
    fetch_fear_greed_history, fear_greed_as_of, render_fear_greed,
)

history = fetch_fear_greed_history()  # una consulta por ejecución
reading = fear_greed_as_of(history, "2024-01-02")
print(render_fear_greed(history, "2024-01-02"))
```

La fecha consultada usa únicamente la lectura del día UTC anterior. Si falta,
falla con `VendorUnavailableError` y no sustituye el dato por otro antiguo.
La API entrega valores actuales de su archivo y su fecha diaria, pero no prueba
la hora original de publicación ni que los valores no hayan sido revisados.
El retraso de un día es una suposición conservadora, no una garantía histórica.

Este índice es un indicador del mercado de Bitcoin que mezcla, entre otros,
volatilidad, volumen y señales sociales. No es un archivo de Reddit o
Stocktwits, ni sentimiento específico de ETH o SOL. Presentarlo como indicador
independiente y etiquetar estas limitaciones en el reporte. Este módulo no lo
inyecta por sí mismo en el grafo ni verifica otras fuentes del backtest.
