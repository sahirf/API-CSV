import React, { useState } from 'react';
import Plot from 'react-plotly.js';
import 'bootstrap/dist/css/bootstrap.min.css';

function CsvPlotUploader() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [plotData, setPlotData] = useState([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [dataInfo, setDataInfo] = useState({
    source: 'Información de la fuente se generará automáticamente o se actualizará aquí.',
    structure: '',
    period: '',
    coverage: ''
  });
  const [analysisTypes, setAnalysisTypes] = useState('');
  const [relevanceReflection, setRelevanceReflection] = useState('');

  const handleFileChange = (event) => {
    setSelectedFile(event.target.files[0]);
    setPlotData([]);
    setError('');
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!selectedFile) {
      setError('Por favor, selecciona un archivo CSV.');
      return;
    }

    setLoading(true);
    setError('');
    setPlotData([]);

    const formData = new FormData();
    formData.append('csv_file', selectedFile);

    try {
      // --- CAMBIO CRÍTICO AQUÍ: Usar URL relativa ---
      // Si el frontend y el backend están en el mismo servicio de Render,
      // la URL del backend será la misma base que la del frontend.
      const backendUrl = '/api/upload-csv'; // Apunta a la ruta API directamente
      // const backendUrl = 'https://prueba-backend-gp8scps06-sahir-segura-serranos-projects.vercel.app'; <-- ESTA URL ES LA QUE DEBEMOS QUITAR
      
      const res = await fetch(backendUrl, {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();

      if (res.ok) {
        const parsedPlots = data.plotly_figures_json.map(figJson => JSON.parse(figJson));
        setPlotData(parsedPlots);
        console.log("Datos de los gráficos de Plotly:", parsedPlots);

        setDataInfo(prevInfo => ({
          ...prevInfo,
          coverage: data.geographic_coverage || 'No se encontró información geográfica disponible para determinar una cobertura específica.'
        }));
        setAnalysisTypes(data.analysis_types || 'No se pudo generar un análisis de los tipos de análisis disponibles.');
        
        setRelevanceReflection('Estas visualizaciones son cruciales para entender rápidamente patrones en los datos, identificar anomalías y comunicar hallazgos complejos de manera efectiva, facilitando la toma de decisiones informadas en áreas como la política pública o la estrategia empresarial.');

      } else {
        setError(data.error || 'Ocurrió un error al subir el archivo.');
      }
    } catch (err) {
      setError('No se pudo conectar con el servidor backend. Asegúrate de que está corriendo.');
      console.error("Error al enviar el archivo:", err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container mt-5">
      <div className="card p-4 shadow-sm">
        <h1 className="mb-4 text-center">Explorador Interactivo de Datos con Gemini AI</h1>
        <hr/>
        
        {/* Sección de Carga de CSV */}
        <h2 className="mb-3">1. Cargar Datos CSV</h2>
        <form onSubmit={handleSubmit}>
          <div className="mb-3">
            <label htmlFor="csvFile" className="form-label">Selecciona tu archivo CSV:</label>
            <input 
              type="file" 
              className="form-control" 
              id="csvFile" 
              accept=".csv" 
              onChange={handleFileChange} 
            />
          </div>
          <button 
            type="submit" 
            className="btn btn-primary w-100" 
            disabled={loading || !selectedFile}
          >
            {loading ? 'Subiendo y generando gráficos...' : 'Subir y Generar Gráficos Interactivos'}
          </button>
        </form>

        {loading && (
          <div className="text-center mt-3">
            <div className="spinner-border text-primary" role="status">
              <span className="visually-hidden">Cargando...</span>
            </div>
            <p className="mt-2">Procesando tu CSV y generando los gráficos interactivos...</p>
          </div>
        )}

        {error && (
          <div className="alert alert-danger mt-3" role="alert">
            {error}
          </div>
        )}

        {/* Sección de Gráficos Interactivos */}
        {plotData.length > 0 && (
          <div className="mt-5">
            <h2 className="mb-3">2. Gráficos Interactivos Generados</h2>
            <p className="text-muted">Explora los gráficos generados. Puedes interactuar con ellos (zoom, pan, selección, etc.).</p>
            <div className="row justify-content-center">
              {plotData.map((figData, index) => (
                <div key={index} className="col-lg-6 col-md-12 mb-4">
                  <div className="card shadow-sm h-100 p-2">
                    <Plot
                      data={figData.data}
                      layout={figData.layout}
                      frames={figData.frames}
                      config={{ responsive: true }}
                      style={{ width: '100%', height: '400px' }}
                    />
                    <div className="card-body text-center">
                        <p className="card-text">Gráfico {index + 1}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <hr className="mt-5"/>

        {/* Sección de Documentación */}
        <div className="mt-5">
          <h2 className="mb-3">3. Documentación del Análisis</h2>
          
          <div className="mb-4">
            <h4>Origen y Estructura de los Datos</h4>
            <p><strong>Fuente:</strong> {dataInfo.source}</p>
            <p><strong>Variables Clave y Estructura:</strong> {dataInfo.structure}</p>
            <p><strong>Periodo:</strong> {dataInfo.period}</p>
            <p><strong>Cobertura Geográfica:</strong> {dataInfo.coverage}</p>
            <p className="text-muted">
                (Nota: La información de origen, estructura y periodo se genera manualmente o podría ser mejorada con más prompts a Gemini.)
            </p>
          </div>

          <div className="mb-4">
            <h4>Tipos de Análisis Disponibles y su Utilidad</h4>
            <p>{analysisTypes}</p>
            <p className="text-muted">
                (Nota: Esta descripción se genera dinámicamente si los gráficos fueron exitosos.)
            </p>
          </div>

          <div>
            <h4>Relevancia de las Visualizaciones en un Contexto Práctico</h4>
            <p>{relevanceReflection}</p>
            <p className="text-muted">
                (Nota: Esta reflexión se genera dinámicamente si los gráficos fueron exitosos.)
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default CsvPlotUploader;