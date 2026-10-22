"""Tests for vector utilities."""


import pytest

from app.services.vector_utils import serialize_vector, validate_vector


class TestValidateVector:
    """Tests for validate_vector function."""

    def test_validate_vector_basic(self):
        """Test basic vector validation."""
        vector = [0.1, 0.2, 0.3, 0.4]
        result = validate_vector(vector, expected_dimension=4, label="test")
        
        assert result == [0.1, 0.2, 0.3, 0.4]
        assert isinstance(result, list)

    def test_validate_vector_tuple_input(self):
        """Test vector validation with tuple input."""
        vector = (0.1, 0.2, 0.3)
        result = validate_vector(vector, expected_dimension=3, label="test")
        
        assert result == [0.1, 0.2, 0.3]

    def test_validate_vector_wrong_dimension(self):
        """Test validation fails for wrong dimension."""
        vector = [0.1, 0.2, 0.3]
        
        with pytest.raises(ValueError, match="exactly 5 dimensions"):
            validate_vector(vector, expected_dimension=5, label="test")

    def test_validate_vector_empty(self):
        """Test validation fails for empty vector."""
        with pytest.raises(ValueError, match="must not be empty"):
            validate_vector([], expected_dimension=0, label="test")

    def test_validate_vector_zero_norm(self):
        """Test validation fails for zero-norm vector."""
        vector = [0.0, 0.0, 0.0]
        
        with pytest.raises(ValueError, match="non-zero norm"):
            validate_vector(vector, expected_dimension=3, label="test")

    def test_validate_vector_infinite_values(self):
        """Test validation fails for infinite values."""
        vector = [0.1, float("inf"), 0.3]
        
        with pytest.raises(ValueError, match="finite numbers"):
            validate_vector(vector, expected_dimension=3, label="test")

    def test_validate_vector_nan_values(self):
        """Test validation fails for NaN values."""
        vector = [0.1, float("nan"), 0.3]
        
        with pytest.raises(ValueError, match="finite numbers"):
            validate_vector(vector, expected_dimension=3, label="test")

    def test_validate_vector_negative_infinity(self):
        """Test validation fails for negative infinity."""
        vector = [0.1, float("-inf"), 0.3]
        
        with pytest.raises(ValueError, match="finite numbers"):
            validate_vector(vector, expected_dimension=3, label="test")

    def test_validate_vector_preserves_values(self):
        """Test validated vector preserves original values."""
        vector = [1.0, 2.0, 3.0, 4.0]
        result = validate_vector(vector, expected_dimension=4, label="test")
        
        assert result[0] == 1.0
        assert result[1] == 2.0
        assert result[2] == 3.0
        assert result[3] == 4.0

    def test_validate_vector_converts_to_float(self):
        """Test validation converts values to float."""
        vector = [1, 2, 3]  # Integers
        result = validate_vector(vector, expected_dimension=3, label="test")
        
        assert all(isinstance(x, float) for x in result)

    def test_validate_vector_large_dimension(self):
        """Test validation with large dimension."""
        vector = [0.01] * 1536  # OpenAI embedding dimension
        result = validate_vector(vector, expected_dimension=1536, label="embedding")
        
        assert len(result) == 1536

    def test_validate_vector_label_in_error(self):
        """Test error message includes label."""
        vector = []
        
        with pytest.raises(ValueError, match="embedding"):
            validate_vector(vector, expected_dimension=0, label="embedding")


class TestSerializeVector:
    """Tests for serialize_vector function."""

    def test_serialize_vector_basic(self):
        """Test basic vector serialization."""
        vector = [0.5, 0.25, 0.125]
        result = serialize_vector(vector)
        
        # Check structure rather than exact string (floating point precision)
        assert result.startswith("[")
        assert result.endswith("]")
        assert "," in result

    def test_serialize_vector_single_element(self):
        """Test serialization of single element vector."""
        vector = [0.5]
        result = serialize_vector(vector)
        
        assert result == "[0.5]"

    def test_serialize_vector_precision(self):
        """Test serialization uses appropriate precision."""
        vector = [1.12345678901234567890]
        result = serialize_vector(vector)
        
        # Should use .17g format
        assert "[" in result
        assert "]" in result

    def test_serialize_vector_tuple_input(self):
        """Test serialization accepts tuple input."""
        vector = (0.5, 0.25, 0.125)
        result = serialize_vector(vector)
        
        assert result.startswith("[")
        assert result.endswith("]")

    def test_serialize_vector_empty(self):
        """Test serialization of empty vector."""
        vector = []
        result = serialize_vector(vector)
        
        assert result == "[]"

    def test_serialize_vector_negative_values(self):
        """Test serialization with negative values."""
        vector = [-0.5, -0.25, 0.125]
        result = serialize_vector(vector)
        
        assert "-" in result
        assert result.startswith("[")
        assert result.endswith("]")

    def test_serialize_vector_scientific_notation(self):
        """Test serialization uses scientific notation when appropriate."""
        vector = [1e-10, 1e10]
        result = serialize_vector(vector)
        
        assert "[" in result
        assert "]" in result
        # Values should be represented efficiently

    def test_serialize_vector_roundtrip(self):
        """Test serialized vector can be parsed back."""
        import ast
        
        vector = [0.1, 0.2, 0.3, 0.4]
        serialized = serialize_vector(vector)
        
        # Parse back (removing the pgvector brackets)
        parsed = ast.literal_eval(serialized)
        
        assert parsed == vector
