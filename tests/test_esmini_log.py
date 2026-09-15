"""Tests for esmini_log module."""

import pytest
from pathlib import Path
from scenario_studio.esmini_log import read_esmini_csv


class TestEsminiLog:
    """Tests for CSV parser."""

    def test_read_esmini_csv(self, tmp_path):
        """Test reading a minimal esmini CSV."""
        # Create a minimal test CSV
        csv_content = """esmini GIT REV: abc123
esmini GIT TAG: v3.7.2
esmini BUILD VERSION: 1234
Scenario File Name: test.xosc
Number of Vehicles: 2
Index,Time,#0.entity_name,#0.entity_id,#0.speed,#0.bb_length,#0.bb_width,#0.x,#0.y,#0.z,#0.vx,#0.vy,#0.vz,#0.ax,#0.ay,#0.az,#0.heading,#0.wheel_angle,#0.wheel_rotation,#0.bb_x,#0.bb_y,#0.bb_z,#0.s,#0.lateral_distance,#0.lane_id,#0.lane_offset,#0.heading_rate,#0.rel_heading,#0.rel_heading_drive_dir,#0.pitch,#0.road_curvature,#0.collision_ids,#1.entity_name,#1.entity_id,#1.speed,#1.bb_length,#1.bb_width,#1.x,#1.y,#1.z,#1.vx,#1.vy,#1.vz,#1.ax,#1.ay,#1.az,#1.heading,#1.wheel_angle,#1.wheel_rotation,#1.bb_x,#1.bb_y,#1.bb_z,#1.s,#1.lateral_distance,#1.lane_id,#1.lane_offset,#1.heading_rate,#1.rel_heading,#1.rel_heading_drive_dir,#1.pitch,#1.road_curvature,#1.collision_ids,
0,0.0,Ego,0,0.0,4.5,1.8,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,-1,0.0,0.0,0.0,0.0,0.0,0.0,,Target,1,0.0,4.5,1.8,10.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,-1,0.0,0.0,0.0,0.0,0.0,,
1,0.05,Ego,0,0.1,4.5,1.8,0.05,0.0,0.0,0.1,0.0,0.0,2.0,0.0,0.0,0.0,0.0,0.0,0.05,0.0,0.0,0.05,0.0,-1,0.0,0.0,0.0,0.0,0.0,0.0,,Target,1,0.0,4.5,1.8,10.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0,-1,0.0,0.0,0.0,0.0,0.0,,
"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(csv_content)

        # Parse the CSV
        df, meta = read_esmini_csv(csv_file)

        # Check metadata
        assert meta["esmini_version"] == "v3.7.2"
        assert meta["esmini_build"] == "1234"
        assert meta["n_entities"] == "2"

        # Check data structure
        assert len(df) == 4  # 2 timesteps × 2 entities
        assert "t" in df.columns
        assert "entity_name" in df.columns
        assert "speed" in df.columns

        # Check data values
        ego_rows = df[df["entity_name"] == "Ego"]
        assert len(ego_rows) == 2
        assert ego_rows.iloc[0]["speed"] == 0.0
        assert ego_rows.iloc[1]["speed"] == 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
