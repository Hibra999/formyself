# Datos de investigación

El flujo preliminar combina precios diarios de Yahoo, noticias de Alpaca,
CPI y tasa de fondos federales de FRED, el índice Bitcoin Fear & Greed de
Alternative.me y eventos GDELT. No reproduce publicaciones históricas de
Reddit o Stocktwits. El índice es un indicador de Bitcoin, no de ETH o SOL.

Las noticias se recortan por publicación y última revisión. FRED usa el
vintage del día anterior. Fear & Greed usa la lectura del día anterior;
GDELT usa el archivo de registros incorporados dos días antes. Sus fechas
reales de publicación y revisiones históricas no están verificadas. Los
eventos GDELT pudieron ocurrir antes de su incorporación al archivo.

La preparación falla si una fuente esencial no responde o no tiene datos
utilizables. Las entradas seleccionadas se entregan como contexto a los
agentes, pero estos pueden consultar otras herramientas y el flujo no
demuestra qué información usó cada modelo. Los resultados deben etiquetarse
como investigación con cobertura parcial, no como prueba de operación real.
