# Verificar snapshots de noticias

Con `TRADINGAGENTS_ALPACA_NEWS_SNAPSHOTS=true`, el adaptador guarda snapshots
JSON bajo `results_dir/reports/alpaca_news_snapshots`, nombrados por SHA256. Esa
carpeta está excluida de Git. Los snapshots guardan noticias, no credenciales.

Después de ejecutar `TradingAgentsGraph.propagate`, inspecciona el `final_state`
devuelto por el grafo:

```python
from pathlib import Path
from tradingagents.snapshot_verification import inspect_graph_report_snapshots

snapshots = Path(config["results_dir"]) / "reports" / "alpaca_news_snapshots"
references = inspect_graph_report_snapshots(snapshots, final_state)
print(references)
```

La función busca encabezados literales de Alpaca en los campos `news_report` y
`sentiment_report`; comprueba los archivos nombrados con esos hashes y separa
`verified`, `missing` e `invalid`. Una lista vacía significa que no encontró
el encabezado; no demuestra que el grafo haya omitido la herramienta. El modelo
puede resumir, omitir o inventar encabezados, por lo que una referencia en el
informe tampoco demuestra qué datos recibió o utilizó el modelo.

Para comprobar un snapshot específico, usa `load_alpaca_snapshot(directory,
digest)`. Para verificar además rango, símbolo, paginación y fechas, usa
`audit_stored_alpaca_snapshot(directory, digest, start, decision_time,
expected_symbol=...)` con fechas conscientes de zona horaria. El resultado
`pagination_consistent` comprueba el objeto guardado, no autentica su origen ni
prueba que la fuente contenga todas las noticias.

Esto no abre el gate del backtest: todavía faltan vincular al grafo los datos
efectivamente usados y verificar las demás fuentes, incluidos precios, FRED y
sentimiento social. No se debe usar una referencia aislada como evidencia de
cobertura completa ni como autorización para operar.
