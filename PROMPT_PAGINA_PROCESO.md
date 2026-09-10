# Prompt: diapositiva del modulo de seguimiento POAI

Prompt listo para pegar. Produce **una sola lamina vertical de PowerPoint (A4 en pie)**
que presenta el desarrollo del modulo de seguimiento POAI en cuatro puntos: que se hizo,
como, que resultado dio y que habilidades puso en juego.

El formato vertical es deliberado: los cuatro puntos son una secuencia y en vertical se
leen bajando, sin repartirlos en cuadrantes. Si la pieza se fuera a proyectar en sala en
vez de leerse o imprimirse, conviene volver a 16:9.

## Que adjuntar junto al prompt

| Archivo | Para que |
|---|---|
| `data/notebook/siifweb_contexto.md` | el analisis en polars que precede a la aplicacion. Da la sustancia tecnica del punto "Como": el grano de la informacion, las llaves de cruce entre reportes y el consolidado por proyecto y vigencia. Existe tambien como `.ipynb` al lado |
| `CONTEXTO.md` | el inventario de reportes de SIIFWEB y el modelo de la cadena del gasto |
| `NOTAS_CRUCES.md` | las reglas de cruce verificadas contra los datos |
| `seguimiento_poai/README.md` | como quedo la aplicacion: cargas, ficha de ejecucion, reporte financiero, dashboard por dependencia y roles de acceso |
| Capturas de pantalla | las entrega el usuario; ver "Las imagenes" al final del prompt |

---

## El prompt

> Diseña **una lamina vertical de PowerPoint, formato A4 en pie**, que presente el
> desarrollo del modulo de seguimiento POAI de la Gobernacion de Sucre. Es una pieza
> profesional para leerse de cerca, imprimirse o anexarse a un documento, y se recorre de
> arriba abajo.
>
> **Tienes libertad creativa en la composicion.** Lo que sigue fija el contenido, el tono y
> las restricciones tecnicas; el reparto visual, la metafora grafica y la jerarquia son
> decision tuya. Sorprendeme, pero sin sacrificar legibilidad.
>
> ### Los cuatro puntos
>
> **1. Que.** Desarrollo del modulo de seguimiento del POAI: una aplicacion web que reune,
> en un solo lugar, la ejecucion presupuestal de los proyectos de inversion y su
> contratacion publica, para que el equipo de seguimiento consulte por si mismo el estado
> de cada proyecto.
>
> **2. Como.** Por medio de programacion. El trabajo empezo entendiendo los reportes de la
> plataforma SIIFWEB: cuales servian, como se comunican entre si y con que llaves se
> cruzan. Ese analisis se hizo primero en un notebook de Python, y sobre esas reglas se
> construyo despues la aplicacion web, que carga los reportes, los valida y los presenta.
> A este punto se anexan **capturas del codigo del notebook** (las entrega el usuario).
>
> **3. Resultado.** Seguimiento actualizado del flujo presupuestal de los proyectos del
> POAI y de los procesos y contratos registrados en SECOP II, en una sola herramienta y al
> alcance del equipo. Lo que antes exigia cruzar reportes a mano, hoy se consulta en
> pantalla. A este punto se anexan **capturas de la aplicacion** (las entrega el usuario).
>
> **4. Habilidades.** Tres, con su justificacion en una linea cada una:
> - **Iniciativa:** dispuse del tiempo y el esfuerzo para entender y utilizar las
>   herramientas adecuadas para construir el aplicativo.
> - **Escucha activa y empatia:** supe entender las necesidades de acceso a la informacion
>   por parte del equipo.
> - **Creatividad:** puse en practica conocimientos previos y enlace el uso de distintas
>   herramientas para resolver el problema.
>
> ### Tono
>
> Espanol, sobrio y directo. Sin frases grandilocuentes, sin metaforas sostenidas y sin
> adjetivos de folleto. En una diapositiva el texto es escaso por definicion: titulos
> cortos y una o dos lineas por punto. Si un bloque pide mas explicacion, dale un grafico
> en vez de mas texto. Que se entienda sin saber programar.
>
> ### Diseno
>
> - **Lienzo:** vertical, proporcion A4 (1:1,41). Trabaja a 1240 x 1754 px o a 2480 x 3508
>   si quieres calidad de impresion, con margen de seguridad de al menos 60 px por lado.
>   Una sola lamina; no la partas en varias. En PowerPoint esto es Diseño → Tamaño de
>   diapositiva → Personalizar → Vertical.
> - **No mas estrecho que eso:** las capturas de la aplicacion son apaisadas -el dashboard
>   es una tabla ancha-. En un lienzo tipo 9:16 quedarian en una banda delgada e ilegible.
>   A4 baja lo suficiente para la secuencia y conserva ancho para que las capturas se lean.
> - **Escalable:** la lamina se vera en pantalla, impresa y quiza reducida dentro de otro
>   documento, y PowerPoint escala todo el conjunto. Trabaja en vectores -SVG inline y
>   CSS-, sin imagenes de mapa de bits salvo las capturas que aporta el usuario, y con
>   tamanos relativos al lienzo, no absolutos. El texto mas pequeno no debe bajar del
>   equivalente a 11 pt sobre A4.
> - **Cuatro franjas que se leen bajando:** el orden 1-2-3-4 tiene que entenderse sin
>   explicacion. Numeralas en grande y dales un hilo visual que las una, para que se lea
>   como un recorrido y no como cuatro recuadros apilados.
> - **Estatico:** nada que dependa de pasar el mouse, hacer clic o desplegar. Debe verse
>   igual exportado a PNG o PDF y pegado en PowerPoint.
> - **Graficos:** si dibujas algo -la cadena del gasto, el cruce entre las dos fuentes de
>   informacion, el recorrido del dato hasta la pantalla-, hazlo en SVG propio. Nada de
>   iconos genericos ni ilustraciones de archivo.
> - **Color:** el verde institucional `#109D39` funciona bien como primario sobre fondo
>   claro, pero tienes libertad para proponer otra paleta si la justificas. El contraste
>   debe aguantar impresion en blanco y negro.
>
> ### Las imagenes
>
> El usuario aporta dos grupos de capturas:
>
> - **De la aplicacion**, para el punto 3: el dashboard de gestion por dependencia, la
>   ficha de ejecucion de un proyecto y el listado de proyectos.
> - **Del codigo del notebook**, para el punto 2.
>
> Mientras no lleguen, deja marcos vacios con la proporcion definitiva reservada y un pie
> de foto de una linea, para que la lamina ya se vea completa y no se desacomode al
> insertarlas. Reserva a las capturas de la aplicacion el ancho util completo del lienzo:
> son apaisadas y es lo que les da legibilidad. Cuando el usuario las entregue, colocalas
> sin rehacer el resto.
>
> ### Lo que no debe aparecer
>
> - **Ninguna cifra de los reportes** -numero de documentos, montos, cantidad de proyectos-.
>   El publico de esta diapositiva no va a detenerse en esos datos y restan foco a los
>   cuatro puntos.
> - **Nada pendiente ni en proceso.** Lo presentado esta funcionando y con los datos al dia.
> - **Nombres de tecnologias como protagonistas.** Pueden mencionarse al pasar, pero el
>   tema es el trabajo hecho y su utilidad, no la herramienta.
> - **Autobombo.** Las habilidades se enuncian con su justificacion, en primera persona y
>   sin superlativos. El resultado habla por si solo.
