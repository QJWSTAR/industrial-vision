"""Unit tests for Service and Repository layers.

Covers:
    - ValidationService (parameter validation)
    - FileRepository (I/O operations)
    - MaterialRepository (material data access)
    - FileService (high-level file operations)

Note: WorkflowController tests removed — class was dead code and has been deleted.
"""

import json
import os
import tempfile
import pytest
import numpy as np

from repair_app.service.validation_service import ValidationService
from repair_app.repository.file_repository import FileRepository
from repair_app.repository.material_repository import MaterialRepository
from repair_app.service.file_service import FileService
from repair_app.domain.models import ProcessParams, PointCloud, DefectRegion


# ================================================================
# ValidationService
# ================================================================

class TestValidationService:

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.vs = ValidationService()

    def test_valid_params(self):
        params = ProcessParams()
        is_valid, errors = self.vs.validate_params(params)
        assert is_valid
        assert len(errors) == 0

    def test_invalid_layer_height(self):
        params = ProcessParams(layer_height_mm=0.001)
        is_valid, errors = self.vs.validate_params(params)
        assert not is_valid
        assert "layer_height_mm" in errors[0]

    def test_invalid_num_layers(self):
        params = ProcessParams(num_layers=300)
        is_valid, errors = self.vs.validate_params(params)
        assert not is_valid

    def test_invalid_particle_velocity(self):
        params = ProcessParams(particle_velocity_ms=50.0)
        is_valid, errors = self.vs.validate_params(params)
        assert not is_valid

    def test_valid_point_cloud(self):
        xyz = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        pc = PointCloud(xyz=xyz)
        is_valid, msg = self.vs.validate_point_cloud(pc)
        assert is_valid
        assert msg == ""

    def test_empty_point_cloud(self):
        pc = PointCloud(xyz=np.zeros((0, 3), dtype=np.float32))
        is_valid, msg = self.vs.validate_point_cloud(pc)
        assert not is_valid

    def test_nan_point_cloud(self):
        xyz = np.array([[1, 2, np.nan]], dtype=np.float32)
        pc = PointCloud(xyz=xyz)
        is_valid, msg = self.vs.validate_point_cloud(pc)
        assert not is_valid

    def test_valid_defect_selection(self):
        xyz = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        pc = PointCloud(xyz=xyz)
        mask = np.array([True, False])
        defect = DefectRegion(mask=mask)
        is_valid, msg = self.vs.validate_defect_selection(pc, defect)
        assert is_valid

    def test_empty_defect_selection(self):
        xyz = np.array([[1, 2, 3]], dtype=np.float32)
        pc = PointCloud(xyz=xyz)
        mask = np.array([False])
        defect = DefectRegion(mask=mask)
        is_valid, msg = self.vs.validate_defect_selection(pc, defect)
        assert not is_valid

    def test_known_material(self):
        is_valid, msg = self.vs.validate_material("STEEL_316L")
        assert is_valid

    def test_unknown_material(self):
        is_valid, msg = self.vs.validate_material("UNOBTAINIUM")
        assert not is_valid


# ================================================================
# FileRepository
# ================================================================

class TestFileRepository:

    @pytest.fixture(autouse=True)
    def _setup(self):
        self._tmp = tempfile.TemporaryDirectory()
        # Override pointlist/velocitylist paths to use temp dir
        self.repo = FileRepository(morph_dir=self._tmp.name)
        self.repo._pointlist_path = os.path.join(self._tmp.name, "pointlist.npz")
        self.repo._velocitylist_path = os.path.join(self._tmp.name, "velocitylist.npz")
        yield
        self._tmp.cleanup()

    def test_save_and_load_waypoints(self):
        waypoints = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        self.repo.save_waypoints(waypoints)
        loaded = self.repo.load_waypoints()
        assert loaded is not None
        np.testing.assert_array_equal(waypoints, loaded)

    def test_save_waypoints_with_velocity(self):
        waypoints = np.array([[1, 2, 3]], dtype=np.float32)
        vel = ["v500", "v300"]
        self.repo.save_waypoints(waypoints, vel)
        vel_path = os.path.join(self._tmp.name, "velocitylist.json")
        assert os.path.exists(vel_path)
        with open(vel_path) as f:
            data = json.load(f)
        assert data == vel

    def test_load_nonexistent_waypoints(self):
        result = self.repo.load_waypoints()
        assert result is None

    def test_has_saved_waypoints(self):
        assert not self.repo.has_saved_waypoints()
        self.repo.save_waypoints(np.array([[1, 2, 3]], dtype=np.float32))
        assert self.repo.has_saved_waypoints()

    def test_load_point_cloud_csv(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("1,2,3,0,0,1\n4,5,6,0,0,1\n")
            path = f.name
        try:
            xyz, normals = FileRepository.load_point_cloud(path)
            assert xyz.shape == (2, 3)
            assert normals is not None
            assert normals.shape == (2, 3)
        finally:
            os.unlink(path)

    def test_load_point_cloud_no_normals(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("1,2,3\n4,5,6\n")
            path = f.name
        try:
            xyz, normals = FileRepository.load_point_cloud(path)
            assert xyz.shape == (2, 3)
            assert normals is None
        finally:
            os.unlink(path)


# ================================================================
# FileService
# ================================================================

class TestFileService:

    @pytest.fixture(autouse=True)
    def _setup(self):
        self._tmp = tempfile.TemporaryDirectory()
        repo = FileRepository(morph_dir=self._tmp.name)
        repo._pointlist_path = os.path.join(self._tmp.name, "pointlist.npz")
        repo._velocitylist_path = os.path.join(self._tmp.name, "velocitylist.npz")
        self.fs = FileService(file_repo=repo)
        yield
        self._tmp.cleanup()

    def test_load_point_cloud_unsupported_format(self):
        with pytest.raises(ValueError):
            self.fs.load_point_cloud("test.stl")

    def test_load_point_cloud_empty_path(self):
        with pytest.raises(ValueError):
            self.fs.load_point_cloud("")

    def test_save_and_load_waypoints_roundtrip(self):
        waypoints = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        assert self.fs.save_waypoints(waypoints)
        assert self.fs.has_saved_waypoints()
        loaded = self.fs.load_waypoints()
        np.testing.assert_array_equal(waypoints, loaded)

    def test_load_waypoints_nonexistent(self):
        assert self.fs.load_waypoints() is None

    def test_morph_dir_property(self):
        assert self.fs.morph_dir == self._tmp.name


# ================================================================
# MaterialRepository
# ================================================================

class TestMaterialRepository:

    def test_get_default_material(self):
        repo = MaterialRepository()
        mat = repo.get_default()
        assert mat is not None

    def test_get_known_material(self):
        repo = MaterialRepository()
        mat = repo.get("STEEL_316L")
        assert mat is not None

    def test_material_keys(self):
        repo = MaterialRepository()
        keys = repo.material_keys
        assert "STEEL_316L" in keys
        assert len(keys) > 0

    def test_unknown_material_returns_default(self):
        repo = MaterialRepository()
        mat = repo.get("NONEXISTENT_MATERIAL")
        default = repo.get_default()
        assert mat == default