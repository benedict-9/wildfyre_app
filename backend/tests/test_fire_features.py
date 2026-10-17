from dataclasses import replace
from datetime import datetime
import pytest
from app.models.features import ModelObservation, build_cell_features
from app.services.firms import FireSnapshot

def utc(value): return datetime.fromisoformat(value.replace("Z","+00:00"))
NOW=utc("2026-10-18T13:05:00Z")
COLUMNS=frozenset("latitude longitude acq_date acq_time satellite confidence bright_ti4 bright_ti5 frp daynight".split())

def observation(id="a",**changes):
    return replace(ModelObservation(id,32.5,-124.5,utc("2026-10-18T06:00:00Z"),
                                     "N","n",330.,290.,10.,"D",None,()),**changes)
def batch(rows,now=NOW,columns=COLUMNS,source="VIIRS_SNPP_NRT"):
    return build_cell_features(FireSnapshot([],rows,columns),now,source)

def test_closed_interval_grid_origin_and_all_features():
    result=batch([observation(),observation("b",frp=30.,brightness4=350.,brightness5=300.,confidence="h",daynight="N")])
    assert result.window_start == utc("2026-10-18T06:00:00Z")
    assert result.window_end == utc("2026-10-18T12:00:00Z")
    assert result.horizon_end == utc("2026-10-19T12:00:00Z")
    # b is a duplicate at the same satellite/place/time: keep first as notebook does.
    assert result.cells[0].features["fire_count"]==1
    result=batch([observation(),observation("b",observed_at=utc("2026-10-18T07:00Z"),
                 frp=30.,brightness4=350.,brightness5=300.,confidence="h",daynight="N")])
    cell=result.cells[0]
    assert cell.id=="0:0" and (cell.grid_x,cell.grid_y)==(0,0)
    assert cell.features=={"fire_count":2,"mean_frp":20,"max_frp":30,
        "mean_bright_ti4":340,"max_bright_ti4":350,"mean_bright_ti5":295,"max_bright_ti5":300,
        "high_confidence_count":1,"normal_confidence_count":1,"day_detection_count":1,
        "night_detection_count":1,"month":10,"hour_utc":6}
    assert result.quality_flags==("nrt_transfer_unvalidated","vegetation_type_unavailable")

def test_stale_open_end_outside_and_filtered_rows_do_not_contribute():
    result=batch([observation(),observation("old",observed_at=utc("2026-10-18T05:59Z")),
        observation("open",observed_at=utc("2026-10-18T12:00Z")),
        observation("outside",longitude=-125),observation("low",confidence="l"),
        observation("other",fire_type=2)])
    assert result.cells[0].fire_ids==("a",)

def test_midnight_previous_day_and_numeric_missing():
    result=batch([observation(observed_at=utc("2026-09-30T18:00Z"),frp=None,brightness4=None)],
                 now=utc("2026-10-01T00:01Z"))
    assert result.cells[0].features["month"]==9
    assert result.cells[0].features["hour_utc"]==18
    assert result.cells[0].features["mean_frp"] is None
    assert result.cells[0].features["max_bright_ti4"] is None

@pytest.mark.parametrize("changes",[{"confidence":""},{"daynight":""},{"satellite":""},
                                     {"problems":("invalid_numeric",)}])
def test_incomplete_contributor_makes_cell_unavailable(changes):
    result=batch([observation(),observation("bad",observed_at=utc("2026-10-18T07:00Z"),**changes)])
    assert result.cells[0].reason=="incomplete_model_inputs"

def test_missing_headers_and_unsupported_product_not_synthetic_empty():
    assert batch([],columns=frozenset()).reason=="missing_model_columns"
    assert batch([],source="MODIS_NRT").reason=="unsupported_source"
    assert batch([]).cells==()
