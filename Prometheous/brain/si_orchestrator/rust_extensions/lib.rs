use pyo3::prelude::*;
use pyo3::wrap_pyfunction;

#[pyfunction]
fn rust_compute_similarity(a: Vec<f64>, b: Vec<f64>) -> PyResult<f64> {
    if a.len() != b.len() {
        return Err(pyo3::exceptions::PyValueError::new_err("Vectors must be same length"));
    }
    let dot: f64 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let norm_a: f64 = a.iter().map(|x| x * x).sum::<f64>().sqrt();
    let norm_b: f64 = b.iter().map(|x| x * x).sum::<f64>().sqrt();
    Ok(dot / (norm_a * norm_b + 1e-8))
}

#[pymodule]
fn si_rust_extensions(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(rust_compute_similarity, m)?)?;
    Ok(())
}