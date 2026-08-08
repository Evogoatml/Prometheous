//! Phase 2 placeholder for high-performance associative memory.
//! Python currently uses `HopfieldMemoryBackend` (pure Python).
//! Future: PyO3 bindings exposing the same store/recall contract.

/// Dot product of two equal-length f64 slices.
pub fn dot(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b.iter()).map(|(x, y)| x * y).sum()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dot_basic() {
        assert!((dot(&[1.0, 0.0], &[1.0, 0.0]) - 1.0).abs() < 1e-9);
    }
}
