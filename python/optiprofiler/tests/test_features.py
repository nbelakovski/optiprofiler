import numpy as np
import pytest

from optiprofiler.features import Feature


class TestFeature:

    @staticmethod
    def rosen(x):
        return np.sum(1e2 * (x[1:] - x[:-1] ** 2) ** 2 + (1.0 - x[:-1]) ** 2)

    @pytest.mark.parametrize('n', [1, 10, 100])
    @pytest.mark.parametrize('seed', [0, 1, 2])
    def test_plain(self, n, seed):
        # Generate random data.
        rng = np.random.default_rng(seed)
        x = rng.standard_normal(n)
        f = self.rosen(x)

        # Test the plain feature.
        feature = Feature('plain')
        assert feature.name == 'plain'
        assert feature.options == {'n_runs': 1}
        assert feature.modifier(x, f) == f

    @pytest.mark.parametrize('n', [1, 10, 100])
    @pytest.mark.parametrize('seed', [0, 1, 2])
    def test_noisy(self, n, seed):
        # Generate random data.
        rng = np.random.default_rng(seed)
        x = rng.standard_normal(n)
        f = self.rosen(x)

        # Test the noisy feature.
        feature = Feature('noisy')
        assert feature.name == 'noisy'
        assert 'distribution' in feature.options and feature.options['type'] == 'relative'
        assert feature.options['n_runs'] == 10
        feature.modifier(x, f)

        # Add custom options.
        feature = Feature('noisy', distribution=lambda rng: 1.0, type='absolute', n_runs=5)
        assert feature.name == 'noisy'
        assert 'distribution' in feature.options and feature.options['type'] == 'absolute'
        assert feature.options['n_runs'] == 5
        np.testing.assert_allclose(feature.modifier(x, f),  f + 1.0)

    @pytest.mark.parametrize('n', [1, 10, 100])
    @pytest.mark.parametrize('seed', [0, 1, 2])
    def test_truncated(self, n, seed):
        # Generate random data.
        rng = np.random.default_rng(seed)
        x = rng.standard_normal(n)
        f = self.rosen(x)

        # Test the truncated feature.
        feature = Feature('truncated')
        assert feature.name == 'truncated'
        assert feature.options == {'n_runs': 10, 'significant_digits': 6}
        np.testing.assert_allclose(feature.modifier(x, f),  f, 1e-5, 1e-5)
        np.testing.assert_allclose(feature.modifier(x, -f),  -f, 1e-5, 1e-5)

        # Add custom options.
        feature = Feature('truncated', significant_digits=4)
        assert feature.name == 'truncated'
        assert feature.options == {'n_runs': 10, 'significant_digits': 4}
        np.testing.assert_allclose(feature.modifier(x, f),  f, 1e-3, 1e-3)

    @pytest.mark.parametrize('n', [1, 10, 100])
    @pytest.mark.parametrize('seed', [0, 1, 2])
    def test_random_nan(self, n, seed):
        # Generate random data.
        rng = np.random.default_rng(seed)
        x = rng.standard_normal(n)
        f = self.rosen(x)

        # Test the random_nan feature.
        feature = Feature('random_nan')
        assert feature.name == 'random_nan'
        assert feature.options == {'n_runs': 10, 'rate_nan': 0.05}
        f_random_nan = feature.modifier(x, f)
        assert f_random_nan == f or np.isnan(f_random_nan)

        # Add custom options.
        feature = Feature('random_nan', rate_nan=0.5)
        assert feature.name == 'random_nan'
        assert feature.options == {'n_runs': 10, 'rate_nan': 0.5}
        try:
            f_random_nan = feature.modifier(x, f)
            assert f_random_nan == f or np.isnan(f_random_nan)
        except RuntimeError:
            pass

    @pytest.mark.parametrize('n', [1, 10, 100])
    @pytest.mark.parametrize('seed', [0, 1, 2])
    def test_custom(self, n, seed):
        # Generate random data.
        rng = np.random.default_rng(seed)
        x = rng.standard_normal(n)
        f = self.rosen(x)

        # Test the custom feature.
        feature = Feature('custom', modifier=lambda x, f, seed: f + 1.0)
        assert feature.name == 'custom'
        assert 'modifier' in feature.options
        assert feature.options['n_runs'] == 1
        np.testing.assert_allclose(feature.modifier(x, f),  f + 1.0)

    def test_exceptions(self):
        with pytest.raises(TypeError):
            Feature(1)
        with pytest.raises(ValueError):
            Feature('unknown')
        with pytest.raises(ValueError):
            Feature('plain', parameter=1.0)
        with pytest.raises(TypeError):
            Feature('noisy', n_runs=1.5)
        with pytest.raises(ValueError):
            Feature('noisy', n_runs=-1)
        with pytest.raises(TypeError):
            Feature('custom', modifier=1.0)
        with pytest.raises(TypeError):
            Feature('noisy', distribution=1.0)
        with pytest.raises(TypeError):
            Feature('random_nan', rate_nan='1.0')
        with pytest.raises(ValueError):
            Feature('random_nan', rate_nan=-1.0)
        with pytest.raises(ValueError):
            Feature('random_nan', rate_nan=2.0)
        with pytest.raises(TypeError):
            Feature('truncated', significant_digits=2.5)
        with pytest.raises(ValueError):
            Feature('truncated', significant_digits=-1)
        with pytest.raises(TypeError):
            Feature('noisy', type=1)
        with pytest.raises(ValueError):
            Feature('noisy', type='+')
        with pytest.raises(ValueError):
            Feature('custom')
        feature = Feature('custom', modifier=lambda x, f, seed: f + 1.0)
        with pytest.raises(TypeError):
            feature.modifier([0.0, 0.0], 1.0)
        with pytest.raises(TypeError):
            feature.modifier(np.zeros(2), 1)
        with pytest.raises(TypeError):
            feature.modifier(np.zeros(2), 1.0, 1)
        with pytest.raises(TypeError):
            feature.modifier(np.zeros(2), 1.0, 1.0, 1)
        with pytest.raises(TypeError):
            feature.modifier(np.zeros(2), 1.0, 1.0, 1.0, 1)
        with pytest.raises(TypeError):
            feature.modifier(np.zeros(2), 1.0, 1.0, 1.0, 1.0, 1.5)
        with pytest.raises(ValueError):
            feature.modifier(np.zeros(2), 1.0, 1.0, 1.0, 1.0, -1)
        with pytest.raises(TypeError):
            feature.get_default_rng(1.5)
        with pytest.raises(ValueError):
            feature.get_default_rng(-1)
        with pytest.raises(TypeError):
            feature.get_default_rng(0, 'arg')

    def test_catch(self):
        # The value n_runs can be a float.
        Feature('noisy', n_runs=2.0)

        # The value significant_digits can be a float.
        Feature('truncated', significant_digits=2.0)

        # The seed can be a float.
        feature = Feature('plain')
        feature.modifier(np.zeros(2), 1.0, seed=1.0)
        feature.get_default_rng(1.0)
