"""One position's 102-channel DR1 coadded surface brightness via HTTP byte ranges."""

import io
import math
import re
import struct
import time
from concurrent.futures import ThreadPoolExecutor

import astropy.units as u
import numpy as np
import requests
from astropy.coordinates import ICRS, SkyCoord
from astropy.io import fits
from astropy.wcs import WCS
from astropy_healpix import HEALPix

from .config import MIB
from .contracts import Problem
from .upstream import IRSA_CLOUD, TransferBudget, fetch

BLOCK = 2880
SIDE = 512
CHANNELS = 102
TILE_RELEASE = "hips_20261026"
CUBE_REFERENCE = "https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_dr1.html"
BLANK_CHANNELS = {50, 51}


def _header(payload, offset=0):
    for cursor in range(offset, offset + 8 * BLOCK, 80):
        if payload[cursor:cursor + 8] == b"END     ":
            end = offset + math.ceil((cursor + 80 - offset) / BLOCK) * BLOCK
            return fits.Header.fromstring(payload[offset:end].decode("ascii"), sep=""), end
    raise Problem("BAD_CUBE", "The archive cube header is incomplete.")


def _padded_image_size(header):
    size = abs(header["BITPIX"]) // 8 * math.prod(header[f"NAXIS{i}"] for i in range(1, header["NAXIS"] + 1))
    return math.ceil(size / BLOCK) * BLOCK


def coadded_spectrum(source, wavelength_range=None):
    if source is None:
        raise Problem("INVALID_REQUEST", "Choose a fixed sky position for the coadded cube.")
    sky = SkyCoord(source["raDeg"], source["decDeg"], unit="deg", frame="icrs")
    layout = HEALPix(nside=32, order="nested", frame=ICRS())
    tile = int(layout.lonlat_to_healpix(sky.ra, sky.dec))
    directory = tile // 10000 * 10000
    path = f"/dr1/hips5_cube/{TILE_RELEASE}/Norder5/Dir{directory}/Npix{tile}_cube.fits"
    url = f"https://{IRSA_CLOUD}{path}"
    archive_url = f"https://irsa.ipac.caltech.edu/ibe/data/spherex{path}"
    deadline = time.monotonic() + 30
    budget = TransferBudget(64 * MIB, 110)

    def read(session, first, size):
        return fetch(url, limit=size, deadline=deadline, purpose="cube", budget=budget,
                     byte_range=(first, first + size - 1), session=session)

    with requests.Session() as session:
        primary = read(session, 0, 4 * BLOCK)
        _, image_header_offset = _header(primary)
        header, data_offset = _header(primary, image_header_offset)
        signature = tuple(header.get(key) for key in ("EXTNAME", "BITPIX", "NAXIS1", "NAXIS2", "NAXIS3"))
        if signature != ("IMAGE", -32, SIDE, SIDE, CHANNELS) or header.get("BSCALE", 1) != 1 or header.get("BZERO", 0) != 0:
            raise Problem("BAD_CUBE", "The archive cube format changed and requires review.")
        celestial = header.copy()
        spectral_keys = re.compile(r"(?:(?:CTYPE|CRVAL|CRPIX|CDELT|CUNIT|CNAME)3|(?:PS|PV)3_\d+|(?:PC|CD)(?:3_\d+|\d+_3))\Z")
        for key in tuple(celestial):
            if spectral_keys.fullmatch(key):
                del celestial[key]
        celestial["NAXIS"] = 2
        celestial["WCSAXES"] = 2
        celestial.pop("NAXIS3", None)
        x, y = WCS(celestial).celestial.world_to_pixel(sky)
        if not np.isfinite(x + y) or not -0.5 <= x < SIDE - 0.5 or not -0.5 <= y < SIDE - 0.5:
            raise Problem("LOW_OVERLAP", "This position falls outside the cube tile's indexed pixels.")
        data_size = _padded_image_size(header)
        next_hdu = data_offset + data_size
        for hdu_name in ("NHITS", "FLAGS"):
            layer, layer_end = _header(read(session, next_hdu, 6 * BLOCK))
            if layer.get("EXTNAME") != hdu_name or tuple(layer.get(f"NAXIS{i}") for i in range(1, 4)) != (SIDE, SIDE, CHANNELS):
                raise Problem("BAD_CUBE", "The cube's archived data layout changed and requires review.")
            next_hdu += layer_end + _padded_image_size(layer)
        tail = read(session, next_hdu, 4 * BLOCK)
        spectral, _ = _header(tail)
        if spectral.get("EXTNAME") != "SPECTRAL_CHANNELS" or spectral.get("NAXIS2") != CHANNELS:
            raise Problem("BAD_CUBE", "The cube wavelength table does not identify all nominal channels.")
        with fits.open(io.BytesIO(primary[:image_header_offset] + tail)) as hdul:
            table = hdul["SPECTRAL_CHANNELS"].data
            channels = [(float(row["WAVELENGTH"]), float(row["BANDWIDTH"])) for row in table]
            if not all(np.isfinite(wave + width) for wave, width in channels):
                raise Problem("BAD_CUBE", "The cube wavelength table contains invalid channel values.")
    ix, iy = math.floor(x + 0.5), math.floor(y + 0.5)
    lo, hi = wavelength_range or (0.7, 5.1)
    indices = [index for index, (wave, _) in enumerate(channels) if lo <= wave <= hi or index in BLANK_CHANNELS]
    pixel_offset = (iy * SIDE + ix) * 4

    def read_samples(items):
        values = []
        with requests.Session() as session:
            for index in items:
                wave, band = channels[index]
                sample = {"channel": index + 1, "wavelengthUm": wave, "bandwidthUm": band, "startUtc": None,
                          "flux": None, "error": None, "units": "MJy/sr", "archiveUrl": archive_url,
                          "sampleStatus": "missing"}
                if index in BLANK_CHANNELS:
                    sample["reason"] = "Blank dichroic channel in the DR1 cube."
                elif time.monotonic() > deadline - 1:
                    sample["reason"] = "Cube read reached its time budget."
                else:
                    try:
                        value, = struct.unpack(">f", read(session, data_offset + index * SIDE * SIDE * 4 + pixel_offset, 4))
                        if math.isfinite(value):
                            sample.update(flux=value, sampleStatus="measured")
                        else:
                            sample["reason"] = "No data at this position in the coadded channel."
                    except Problem as exc:
                        sample["reason"] = exc.message
                values.append(sample)
        return values

    with ThreadPoolExecutor(max_workers=2) as executor:
        groups = executor.map(read_samples, (indices[::2], indices[1::2]))
        samples = sorted((sample for group in groups for sample in group), key=lambda sample: sample["channel"])
    partial = any(item["sampleStatus"] == "missing" and item["channel"] - 1 not in BLANK_CHANNELS for item in samples)
    warnings = ["DR1 coadded brightness at one sky pixel. This cube has no observation time or per-channel uncertainty."]
    if partial:
        warnings.append("Some channels have no data or could not be read within the job budget.")
    return {"mode": "coadded_cube", "method": "nearest cube pixel", "samples": samples, "partial": partial,
            "units": "MJy/sr", "warnings": warnings, "archiveUrl": archive_url, "archiveDoi": "10.26131/IRSA678",
            "referenceUrl": CUBE_REFERENCE, "transferBytes": budget.bytes}
