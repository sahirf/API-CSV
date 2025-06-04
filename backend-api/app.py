from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS # Sigue importándolo por si lo necesitas, pero lo ajustaremos
import google.generativeai as genai
import pandas as pd
import io
import os
import tempfile
import uuid
import json
import plotly.express as px
import plotly.graph_objects as go

# --- Configuración de Flask para servir archivos estáticos de React ---
# La ruta 'static_folder' es relativa a donde se ejecuta app.py.
# Si app.py está en 'backend/' y 'build' está en 'frontend/', entonces '../frontend/build' es la ruta correcta.
# 'static_url_path='/' hace que Flask sirva los archivos desde la raíz del dominio.
app = Flask(__name__, static_folder='../frontend/build', static_url_path='/')

# --- Configuración de CORS ---
# Cuando el frontend y el backend se sirven desde el mismo origen (Render),
# la política de CORS ya no es necesaria para la comunicación entre ellos.
# Puedes eliminar esta línea o configurarla para permitir todos los orígenes
# si tienes clientes externos o si quieres mantenerla para el desarrollo local.
# Para este despliegue unificado, la forma más sencilla es:
CORS(app) # Esto permite cualquier origen. Es útil para pruebas locales, pero no estrictamente necesario para la comunicación interna.
          # Si quieres ser más restrictivo, podrías quitarlo por completo ya que están en el mismo origen.


# --- Configura tu API Key ---
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY", "AIzaSyBxaTAU260rRwWmJQPjfn_u0yl5aaOl_Gg"))

# --- Define el modelo que vas a usar ---
model = genai.GenerativeModel('gemini-1.5-flash')

# --- Ruta para guardar los JSON de los gráficos generados (no imágenes PNG) ---
# Asegúrate de que esta ruta sea accesible en el entorno de Render
PLOTS_JSON_DIR = os.path.join(app.root_path, 'generated_plots_json')
os.makedirs(PLOTS_JSON_DIR, exist_ok=True)

# --- Ruta para la API de carga de CSV ---
@app.route('/api/upload-csv', methods=['POST'])
def upload_csv():
    if 'csv_file' not in request.files:
        return jsonify({"error": "No se encontró el archivo CSV en la solicitud."}), 400

    csv_file = request.files['csv_file']
    if csv_file.filename == '':
        return jsonify({"error": "No se seleccionó ningún archivo."}), 400

    if csv_file:
        temp_head_csv_file_path = None
        original_csv_local_path = None
        uploaded_file_to_gemini = None
        
        plotly_figures_json = [] 
        analysis_types_output = "" # Para almacenar el análisis de Gemini
        geographic_coverage_output = "" # Para almacenar la cobertura geográfica de Gemini

        try:
            csv_content = csv_file.read().decode('utf-8')
            df_original = pd.read_csv(io.StringIO(csv_content))
            
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.csv', delete=False, dir=app.root_path) as tmp_csv:
                df_original.to_csv(tmp_csv.name, index=False)
                original_csv_local_path = tmp_csv.name 
            
            df_head = df_original.head(5)

            with tempfile.NamedTemporaryFile(mode='w+', suffix='.csv', delete=False) as temp_head_csv_file:
                df_head.to_csv(temp_head_csv_file.name, index=False)
                temp_head_csv_file_path = temp_head_csv_file.name
            
            uploaded_file_to_gemini = genai.upload_file(path=temp_head_csv_file_path)
            print(f"Archivo temporal (head) subido a Gemini. ID: {uploaded_file_to_gemini.name}")

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
            1.  El código que generes debe asumir que cargará el CSV original completo desde un archivo llamado '{os.path.basename(original_csv_local_path)}'.
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

            response_charts = model.generate_content(
                contents=contents_for_gemini_charts,
                request_options={'timeout': 600}
            )
            
            generated_code = response_charts.text
            print(f"Código generado por Gemini:\n{generated_code}")

            cleaned_code = generated_code.replace("```python", "").replace("```", "").strip()
            print(f"Código limpio:\n{cleaned_code}")

            # --- Ejecutar el código generado y capturar las figuras de Plotly ---
            exec_globals = {
                'pd': pd,
                'px': px,
                'go': go, 
                'io': io,
                'os': os,
                'original_csv_file_path': original_csv_local_path,
                'plotly_figures': []
            }
            
            try:
                final_code_to_execute = "plotly_figures = []\n" + cleaned_code 
                exec(final_code_to_execute, exec_globals)
                
                for fig in exec_globals['plotly_figures']:
                    plotly_figures_json.append(fig.to_json())
                
                print(f"Se generaron {len(plotly_figures_json)} figuras de Plotly.")

            except Exception as e:
                return jsonify({"error": f"Error al ejecutar el código generado por Gemini (Plotly): {e}"}), 500

            if not plotly_figures_json:
                return jsonify({"error": "Gemini no generó ninguna figura de Plotly o no las añadió a 'plotly_figures'.", "generated_code": generated_code}), 500

            # --- Segundo Prompt: Generación de Documentación (Análisis y Cobertura Geográfica) ---
            # Aquí combinamos el contexto del CSV con los gráficos generados (usando sus JSON para la descripción)
            # para pedirle a Gemini que haga un análisis y determine la cobertura geográfica.
            
            # Puedes pasar las columnas del DataFrame original para darle más contexto
            column_names = ", ".join(df_original.columns.tolist())
            
            # Convertimos las figuras de Plotly a un formato legible para Gemini
            # Ojo: No le pasamos el JSON completo de todas las figuras, sino una descripción de las columnas,
            # ya que el JSON de figuras puede ser muy grande.
            # Podrías pasar los títulos o tipos de gráficos que se generaron.
            
            charts_description = ""
            if len(exec_globals['plotly_figures']) > 0:
                charts_description = "Se han generado los siguientes tipos de gráficos interactivos: "
                chart_types = set()
                for fig in exec_globals['plotly_figures']:
                    # Intenta extraer el tipo de gráfico del JSON de la figura (puede variar según la complejidad)
                    if fig.data and fig.data[0].type:
                        chart_types.add(fig.data[0].type)
                    elif fig.layout and fig.layout.title and fig.layout.title.text:
                        # Si no hay tipo, al menos usa el título para dar una idea
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
                uploaded_file_to_gemini # Reutilizamos el archivo subido a Gemini para el contexto
            ]

            response_documentation = model.generate_content(
                contents=contents_for_gemini_documentation,
                request_options={'timeout': 300} # Un timeout un poco más corto, ya que es solo texto
            )
            
            documentation_text = response_documentation.text
            print(f"Documentación generada por Gemini:\n{documentation_text}")

            # Parsear la respuesta de Gemini para los campos específicos
            # Esto asume un formato específico en la respuesta de Gemini
            analysis_section_start = documentation_text.find("**Análisis de Datos y Utilidad:**")
            coverage_section_start = documentation_text.find("**Cobertura Geográfica:**")

            if analysis_section_start != -1 and coverage_section_start != -1:
                analysis_types_output = documentation_text[analysis_section_start + len("**Análisis de Datos y Utilidad:**"):coverage_section_start].strip()
                geographic_coverage_output = documentation_text[coverage_section_start + len("**Cobertura Geográfica:**"):].strip()
            else:
                # Si Gemini no sigue el formato exacto, al menos damos la respuesta completa
                analysis_types_output = "No se pudo parsear el análisis de datos. Respuesta completa de Gemini: " + documentation_text
                geographic_coverage_output = "No se pudo parsear la cobertura geográfica. Respuesta completa de Gemini: " + documentation_text

            # Envía la lista de JSON de figuras de Plotly y la nueva documentación al frontend
            return jsonify({
                "status": "success",
                "plotly_figures_json": plotly_figures_json,
                "analysis_types": analysis_types_output,
                "geographic_coverage": geographic_coverage_output
            }), 200

        except pd.errors.EmptyDataError:
            return jsonify({"error": "El archivo CSV está vacío."}), 400
        except Exception as e:
            return jsonify({"error": f"Error al leer o procesar el CSV: {e}"}), 500
        finally:
            # --- Limpieza: Eliminar archivos temporales ---
            if temp_head_csv_file_path and os.path.exists(temp_head_csv_file_path):
                os.remove(temp_head_csv_file_path)
                print(f"Archivo temporal (head para Gemini) local eliminado: {temp_head_csv_file_path}")
            
            if original_csv_local_path and os.path.exists(original_csv_local_path):
                os.remove(original_csv_local_path)
                print(f"Archivo temporal (original para ejecución) local eliminado: {original_csv_local_path}")
            
            if uploaded_file_to_gemini:
                print(f"Eliminando archivo subido de Gemini: {uploaded_file_to_gemini.name}")
                try:
                    genai.delete_file(uploaded_file_to_gemini.name)
                    print("Archivo subido de Gemini eliminado exitosamente.")
                except Exception as e:
                    print(f"Error al eliminar el archivo subido de Gemini: {e}")

    return jsonify({"error": "Error desconocido al procesar el archivo."}), 500

# --- Nueva ruta catch-all para servir el frontend React ---
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    # Esto manejará las rutas de tu SPA de React.
    # Por ejemplo, si vas a /about, React maneja el enrutamiento, pero el servidor
    # debe servir siempre el index.html si no es un archivo estático directo.
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        # Si la ruta apunta a un archivo estático existente (ej. .js, .css, imagen)
        return send_from_directory(app.static_folder, path)
    else:
        # Para cualquier otra ruta (incluyendo la raíz y las rutas de React),
        # sirve el index.html y deja que React Router haga su trabajo.
        return send_from_directory(app.static_folder, 'index.html')

if __name__ == '__main__':
    # Cuando se ejecuta localmente, Flask sirve en el puerto 5000.
    # En Render, Gunicorn maneja el puerto (usualmente 10000).
    app.run(debug=True, port=5000)