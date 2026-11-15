"""Wire inputs, errors, and coordinate normalization."""

from datetime import date, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, model_validator

ID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")]
JOB_ID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
RA = Annotated[float, Field(ge=0, lt=360, allow_inf_nan=False, strict=True)]
Dec = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False, strict=True)]
Wavelength = Annotated[float, Field(ge=0.7, le=5.1, strict=True)]


class Problem(Exception):
    def __init__(self, code, message, status=422, retryable=False, retry_after=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after

    def payload(self):
        data = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if self.retry_after is not None:
            data["retryAfterSec"] = self.retry_after
        return data


def ready(data, warnings=(), partial=False):
    return {"status": "partial" if partial else "succeeded", "data": data, "warnings": list(warnings)}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SeriesQuery(Input):
    raDeg: RA
    decDeg: Dec
    fovArcmin: Annotated[float, Field(ge=1, le=8, strict=True)] = 3.0
    start: date | None = None
    end: date | None = None
    detector: Annotated[StrictInt, Field(ge=1, le=6)] | None = None
    wavelengthUm: Wavelength | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start and self.end:
            if self.end < self.start or self.end > max_range_end(self.start):
                raise ValueError("Choose an ordered UTC date range of at most 24 months.")
        return self

    def normalized(self):
        data = self.model_dump(mode="json", exclude_none=True)
        data["raDeg"] = round(self.raDeg, 7) % 360
        data["decDeg"] = round(self.decDeg, 7) or 0.0
        data["fovArcmin"] = round(self.fovArcmin, 3)
        if abs(data["decDeg"]) == 90:
            data["raDeg"] = 0.0
        if self.wavelengthUm is not None:
            data["wavelengthUm"] = round(self.wavelengthUm, 5)
        return data


def max_range_end(start):
    if start.year > 9997:
        return date.max
    try:
        return start.replace(year=start.year + 2)
    except ValueError:
        return start.replace(year=start.year + 2, day=28) + timedelta(days=1)


class FrameOptions(Input):
    representation: Literal["exposure", "coadd"] = "exposure"
    priority: Literal["interactive", "prefetch"] = "interactive"


class ComparisonQuery(Input):
    frameA: ID
    frameB: ID
    mode: Literal["difference", "absolute_change", "residual_score", "sum"]


class SkyPosition(Input):
    raDeg: RA
    decDeg: Dec


class RecenterQuery(SkyPosition):
    """A nearby center using the existing series' bounds and known exposures."""


class PixelPosition(Input):
    x: Annotated[float, Field(ge=0, lt=128, strict=True)]
    y: Annotated[float, Field(ge=0, lt=128, strict=True)]


class Region(Input):
    x: Annotated[StrictInt, Field(ge=0, lt=128)]
    y: Annotated[StrictInt, Field(ge=0, lt=128)]
    width: Annotated[StrictInt, Field(ge=1, le=128)]
    height: Annotated[StrictInt, Field(ge=1, le=128)]


class DetectionQuery(Input):
    frameIds: Annotated[list[ID], Field(min_length=2, max_length=8)] | None = None
    comparisonId: ID | None = None
    region: Region | None = None

    @model_validator(mode="after")
    def one_selection(self):
        if (self.frameIds is None) == (self.comparisonId is None):
            raise ValueError("Choose frameIds or comparisonId.")
        if self.frameIds and len(set(self.frameIds)) != len(self.frameIds):
            raise ValueError("Choose distinct frame IDs.")
        return self


class Mark(Input):
    frameId: ID
    pixel: PixelPosition | None = None
    sky: SkyPosition | None = None
    centroidPixel: PixelPosition | None = None

    @model_validator(mode="after")
    def one_position(self):
        if (self.pixel is None) == (self.sky is None):
            raise ValueError("Choose pixel or sky coordinates for each mark.")
        if self.centroidPixel is not None and self.pixel is None:
            raise ValueError("Keep the original pixel coordinates when choosing a centroid.")
        return self


class TrackQuery(Input):
    candidateId: ID | None = None
    marks: Annotated[list[Mark], Field(min_length=2, max_length=8)] | None = None
    horizonDays: Annotated[float, Field(gt=0, le=30, strict=True)] | None = None

    @model_validator(mode="after")
    def one_selection(self):
        if (self.candidateId is None) == (self.marks is None):
            raise ValueError("Choose candidateId or marks.")
        return self


class OverlayQuery(Input):
    catalog: Literal["gaia_dr3", "allwise"]
    frameId: ID | None = None


class DateRange(Input):
    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start or self.end > max_range_end(self.start):
            raise ValueError("Choose an ordered UTC date range of at most 24 months.")
        return self


class SpectrumQuery(Input):
    selectedSkyPosition: SkyPosition | None = None
    candidateId: ID | None = None
    timeRange: DateRange | None = None
    wavelengthRange: tuple[Wavelength, Wavelength] | None = None
    method: Literal["epsf", "aperture"] = "aperture"
    mode: Literal["quick", "extended", "coadded_cube"] = "quick"

    @model_validator(mode="after")
    def valid_selection(self):
        if (self.selectedSkyPosition is None) == (self.candidateId is None):
            raise ValueError("Choose one sky position or candidate.")
        if self.wavelengthRange and self.wavelengthRange[0] > self.wavelengthRange[1]:
            raise ValueError("Choose an ordered wavelength range.")
        return self
