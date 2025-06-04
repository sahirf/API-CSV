from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import google.generativeai as genai
import pandas as pd
import io
import os
import tempfile
import uuid
import json
import plotly.express as px
import plotly.graph_objects as go
import logging # <--- AÑADIDO: Importar el módulo logging

# --- Configuración de Logging ---
# Configura el logger para que muestre mensajes INFO y superiores
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Asegúrate de que el logger de Flask también use INFO
app = Flask(__name__, static_folder='../frontend/build', static_url_path='/')
app.logger.setLevel(logging.INFO) # <--- AÑADIDO: Configurar nivel de logging para la app
CORS(app)


# --- Configura tu API Key ---
# Es recomendable usar una clave de prueba si vas a tener un valor por defecto,
# o simplemente dejarlo depender de la variable de entorno para producción.
# genai.configure(api_key=os.environ.get("GOOGLE_API_KEY", "AIzaSyBxaTAU260rRwWmJQPjfn_u0yl5aaOl_Gg"))
# Sugerencia: Para asegurar que siempre toma la de ENV en Render y localmente falla si no está:
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY")) # <--- MODIFICADO: Solo depender de ENV

# --- Define el modelo que vas a usar ---
model = genai.GenerativeModel('gemini-1.5-flash')

# --- Ruta para guardar los JSON de los gráficos generados (no imágenes PNG) ---
PLOTS_JSON_DIR = os.path.join(app.root_path, 'generated_plots_json')
os.makedirs(PLOTS_JSON_DIR, exist_ok=True)

# --- Ruta para la API de carga de CSV ---
@app.route('/api/upload-csv', methods=['POST'])
def upload_csv():
    app.logger.info("Solicitud /api/upload-csv recibida.") # <--- AÑADIDO: Logging
    if 'csv_file' not in request.files:
        app.logger.error("No se encontró el archivo CSV en la solicitud.") # <--- AÑADIDO: Logging
        return jsonify({"error": "No se encontró el archivo CSV en la solicitud."}), 400

    csv_file = request.files['csv_file']
    if csv_file.filename == '':
        app.logger.error("No se seleccionó ningún archivo.") # <--- AÑADIDO: Logging
        return jsonify({"error": "No se seleccionó ningún archivo."}), 400

    if csv_file:
        temp_head_csv_file_path = None
        original_csv_local_path = None # Esta variable ya no se usará en el prompt de Gemini
        uploaded_file_to_gemini = None
        
        plotly_figures_json = [] 
        analysis_types_output = ""
        geographic_coverage_output = ""

        try:
            csv_content = csv_file.read().decode('utf-8')
            df_original = pd.read_csv(io.StringIO(csv_content))
            app.logger.info("CSV cargado en DataFrame df_original.") # <--- AÑADIDO: Logging
            
            # NOTA: La creación de original_csv_local_path y el archivo temporal aquí
            # ya no es estrictamente necesaria si Gemini no lo lee, pero mantenerlo
            # para el exec_globals que aún espera ese path si el código de Gemini lo usara.
            # Sin embargo, el PROMPT de Gemini ya no pedirá que lo cargue.
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.csv', delete=False, dir=app.root_path) as tmp_csv:
                df_original.to_csv(tmp_csv.name, index=False)
                original_csv_local_path = tmp_csv.name 
                app.logger.info(f"Archivo CSV original guardado temporalmente en: {original_csv_local_path}") # <--- AÑADIDO: Logging
            
            df_head = df_original.head(5)

            with tempfile.NamedTemporaryFile(mode='w+', suffix='.csv', delete=False) as temp_head_csv_file:
                df_head.to_csv(temp_head_csv_file.name, index=False)
                temp_head_csv_file_path = temp_head_csv_file.name
                app.logger.info(f"Head del CSV guardado temporalmente para Gemini en: {temp_head_csv_file_path}") # <--- AÑADIDO: Logging
            
            uploaded_file_to_gemini = genai.upload_file(path=temp_head_csv_file_path)
            app.logger.info(f"Archivo temporal (head) subido a Gemini. ID: {uploaded_file_to_gemini.name}") # <--- MODIFICADO: print a app.logger.info

            # --- Primer Prompt: Generación de CÓDIGO PLOTLY INTERACTIVO ---
            user_prompt_charts = f"""
            Este es un archivo CSV, pero solo te he enviado las primeras 5 filas para que entiendas la estructura. 
            El archivo real es mucho más grande y estará disponible para la ejecución del código.

            Aquí tienes el contenido de las primeras 5 filas:
            {df_head.to_string(index=False)}

            Basándote en esta estructura, por favor, genera el código Python usando la librería **Plotly Express** para crear **todos los gráficos interactivos visualmente significativos y diversos que sean posibles**.
            Considera diferentes tipos de gráficos (barras, líneas, dispersión, histogramas, etc.) que puedan revelar 
            información relevante de los datos. Si los datos incluyen series temporales o información geográfica, 
            genera gráficos adecuados para ello (ej. línea de tiempo, mapa coroplético).

            **Importante:**
            1.  El código que generes debe asumir que el CSV original completo ya ha sido cargado en una variable de pandas DataFrame llamada `df_original`. **NO debes usar `pd.read_csv()` ni ninguna otra forma de cargar el archivo.** Simplemente asume que `df_original` está disponible y es tu DataFrame de trabajo.
            2.  Para cada gráfico:
                a.  Crea una figura de Plotly (ej. `fig = px.line(...)` o `fig = go.Figure(...)`).
                b.  **Almacena cada objeto de figura de Plotly en una lista llamada `plotly_figures`.** Por ejemplo, `plotly_figures.append(fig)`. Debes inicializar `plotly_figures = []` al principio del código.
                c.  **NO incluyas `fig.write_html()` o `fig.show()` o `fig.write_image()` ni `fig.savefig()`**. Solo crea y añade las figuras a la lista.
            3.  Asegúrate de importar `plotly.express as px` y `plotly.graph_objects as go` si los usas.
            4.  No incluyas explicaciones, solo el código Python completo y ejecutable.
            """
            contents_for_gemini_charts = [
                user_prompt_charts,
                uploaded_file_to_gemini
            ]
            app.logger.info("Enviando prompt a Gemini para la generación de código de gráficos.") # <--- AÑADIDO: Logging
            response_charts = model.generate_content(
                contents=contents_for_gemini_charts,
                request_options={'timeout': 600}
            )
            
            generated_code = response_charts.text
            app.logger.info(f"Código generado por Gemini:\n{generated_code[:500]}...") # <--- MODIFICADO: print a app.logger.info, truncado para logs
            app.logger.info(f"Código limpio:\n{generated_code.replace('```python', '').replace('```', '').strip()[:500]}...") # <--- MODIFICADO: print a app.logger.info, truncado

            cleaned_code = generated_code.replace("```python", "").replace("```", "").strip()

            # --- Ejecutar el código generado y capturar las figuras de Plotly ---
            exec_globals = {
                'pd': pd,
                'px': px,
                'go': go, 
                'io': io,
                'os': os,
                'original_csv_file_path': original_csv_local_path, # Esto es para referencia, Gemini ya no debería usarlo
                'plotly_figures': [],
                'df_original': df_original # <--- CRUCIAL: Pasar df_original al entorno de ejecución
            }
            app.logger.info("Ejecutando el código generado por Gemini.") # <--- AÑADIDO: Logging
            try:
                final_code_to_execute = "plotly_figures = []\n" + cleaned_code 
                exec(final_code_to_execute, exec_globals)
                
                for fig in exec_globals['plotly_figures']:
                    plotly_figures_json.append(fig.to_json())
                
                app.logger.info(f"Se generaron {len(plotly_figures_json)} figuras de Plotly.") # <--- MODIFICADO: print a app.logger.info

            except Exception as e:
                app.logger.error(f"Error al ejecutar el código generado por Gemini (Plotly): {e}", exc_info=True) # <--- AÑADIDO: Logging con traceback
                return jsonify({"error": f"Error al ejecutar el código generado por Gemini (Plotly): {e}"}), 500

            if not plotly_figures_json:
                app.logger.warning("Gemini no generó ninguna figura de Plotly o no las añadió a 'plotly_figures'.") # <--- AÑADIDO: Logging
                return jsonify({"error": "Gemini no generó ninguna figura de Plotly o no las añadió a 'plotly_figures'.", "generated_code": generated_code}), 500

            # --- Segundo Prompt: Generación de Documentación (Análisis y Cobertura Geográfica) ---
            column_names = ", ".join(df_original.columns.tolist())
            
            charts_description = ""
            if len(exec_globals['plotly_figures']) > 0:
                charts_description = "Se han generado los siguientes tipos de gráficos interactivos: "
                chart_types = set()
                for fig in exec_globals['plotly_figures']:
                    if fig.data and fig.data[0].type:
                        chart_types.add(fig.data[0].type)
                    elif fig.layout and fig.layout.title and fig.layout.title.text:
                        chart_types.add(f"'{fig.layout.title.text}'")
                charts_description += ", ".join(list(chart_types)) + "."
            else:
                charts_description = "No se generaron gráficos."

            # --- NUEVO PROMPT PARA DOCUMENTACIÓN Y ANÁLISIS ---
            user_prompt_documentation = f"""
            Acabas de generar varios gráficos interactivos a partir de un archivo CSV con las siguientes columnas:
            {column_names}
            
            {charts_description}

            Por favor, realiza un análisis conciso y útil de los datos que se pueden inferir o visualizar con estos gráficos.
            
            1.  **Tipos de Análisis Disponibles y su Utilidad:**
                Describe los tipos de análisis que se pueden realizar con estos datos y gráficos (ej. tendencias, correlaciones, distribuciones, comparaciones). Explica brevemente la utilidad práctica de cada tipo de análisis en un contexto de toma de decisiones.

            2.  **Cobertura Geográfica (si aplica):**
                Basándote en las columnas del CSV (ej. 'País', 'Ciudad', 'Región', 'Latitud', 'Longitud') y el contexto general, intenta determinar si los datos tienen una cobertura geográfica específica. Si identificas columnas relacionadas con la geografía, indica qué información sugieren (ej. "Los datos parecen abarcar países a nivel global", "Los datos se centran en regiones de un país específico"). Si no encuentras información geográfica explícita o no puedes determinarla, responde: "No se encontró información geográfica disponible en las columnas de los datos para determinar una cobertura específica."

            Formatea tu respuesta de la siguiente manera:

            **Análisis de Datos y Utilidad:**
            [Tu descripción de los tipos de análisis y su utilidad]

            **Cobertura Geográfica:**
            [Tu descripción de la cobertura geográfica o el mensaje de 'no encontrado']
            """
            
            contents_for_gemini_documentation = [
                user_prompt_documentation,
                uploaded_file_to_gemini
            ]
            app.logger.info("Enviando prompt a Gemini para la documentación.") # <--- AÑADIDO: Logging
            response_documentation = model.generate_content(
                contents=contents_for_gemini_documentation,
                request_options={'timeout': 300}
            )
            
            documentation_text = response_documentation.text
            app.logger.info(f"Documentación generada por Gemini:\n{documentation_text[:500]}...") # <--- MODIFICADO: print a app.logger.info, truncado

            analysis_section_start = documentation_text.find("**Análisis de Datos y Utilidad:**")
            coverage_section_start = documentation_text.find("**Cobertura Geográfica:**")

            if analysis_section_start != -1 and coverage_section_start != -1:
                analysis_types_output = documentation_text[analysis_section_start + len("**Análisis de Datos y Utilidad:**"):coverage_section_start].strip()
                geographic_coverage_output = documentation_text[coverage_section_start + len("**Cobertura Geográfica:**"):].strip()
            else:
                analysis_types_output = "No se pudo parsear el análisis de datos. Respuesta completa de Gemini: " + documentation_text
                geographic_coverage_output = "No se pudo parsear la cobertura geográfica. Respuesta completa de Gemini: " + documentation_text

            app.logger.info("Análisis y cobertura geográfica parseados.") # <--- AÑADIDO: Logging
            return jsonify({
                "status": "success",
                "plotly_figures_json": plotly_figures_json,
                "analysis_types": analysis_types_output,
                "geographic_coverage": geographic_coverage_output
            }), 200

        except pd.errors.EmptyDataError:
            app.logger.error("El archivo CSV está vacío.", exc_info=True) # <--- AÑADIDO: Logging con traceback
            return jsonify({"error": "El archivo CSV está vacío."}), 400
        except Exception as e:
            app.logger.error(f"Error general al leer o procesar el CSV: {e}", exc_info=True) # <--- AÑADIDO: Logging con traceback
            return jsonify({"error": f"Error interno del servidor: {e}"}), 500
        finally:
            # --- Limpieza: Eliminar archivos temporales ---
            if temp_head_csv_file_path and os.path.exists(temp_head_csv_file_path):
                os.remove(temp_head_csv_file_path)
                app.logger.info(f"Archivo temporal (head para Gemini) local eliminado: {temp_head_csv_file_path}") # <--- MODIFICADO: print a app.logger.info
            
            # Este archivo temporal es el que Gemini generaría en su código, pero ahora no debería ser usado por Gemini
            # Y tu código principal (app.py) ya lo cargó en df_original, así que también puede ser eliminado.
            if original_csv_local_path and os.path.exists(original_csv_local_path):
                os.remove(original_csv_local_path)
                app.logger.info(f"Archivo temporal (original para ejecución) local eliminado: {original_csv_local_path}") # <--- MODIFICADO: print a app.logger.info
            
            if uploaded_file_to_gemini:
                app.logger.info(f"Eliminando archivo subido de Gemini: {uploaded_file_to_gemini.name}") # <--- MODIFICADO: print a app.logger.info
                try:
                    genai.delete_file(uploaded_file_to_gemini.name)
                    app.logger.info("Archivo subido de Gemini eliminado exitosamente.") # <--- MODIFICADO: print a app.logger.info
                except Exception as e:
                    app.logger.error(f"Error al eliminar el archivo subido de Gemini: {e}", exc_info=True) # <--- AÑADIDO: Logging con traceback

    app.logger.error("Error desconocido al procesar el archivo (fuera de los bloques try).") # <--- AÑADIDO: Logging
    return jsonify({"error": "Error desconocido al procesar el archivo."}), 500

# --- Nueva ruta catch-all para servir el frontend React ---
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    app.run(debug=True, port=5000)