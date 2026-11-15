"""Produce a reduced official detector-map index for metadata shortlisting only."""

from argparse import ArgumentParser
from pathlib import Path

import numpy as np
from astropy.io import fits
from scipy.ndimage import map_coordinates

VERSION = 'cal-swcs-v5-2026-191'


def create(source, destination):
    row, col = np.meshgrid(np.linspace(0, 2039, 65), np.linspace(0, 2039, 65), indexing='ij')
    wavelength, bandwidth = [], []
    for detector in range(1, 7):
        local = source / f'spherex-wcs-D{detector}.fits'
        with fits.open(local, memmap=True) as hdul:
            for layer, values in [('CWAVE', wavelength), ('CBAND', bandwidth)]:
                hdu = hdul[layer]
                if hdu.shape != (2040, 2040) or hdu.header.get('DETCOORD') != 'sky':
                    raise ValueError(f'Unsupported detector map {detector}: {layer}')
                values.append(map_coordinates(hdu.data, [row, col], order=1).astype(np.float32))
    np.savez_compressed(destination, wavelength=wavelength, bandwidth=bandwidth, calibration=VERSION)


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    create(args.source, args.destination)
