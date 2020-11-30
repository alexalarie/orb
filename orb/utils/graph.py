#!/usr/bin/python
# *-* coding: utf-8 *-*
# Author: Thomas Martin <thomas.martin.1@ulaval.ca>
# File: image.py

## Copyright (c) 2010-2020 Thomas Martin <thomas.martin.1@ulaval.ca>
## 
## This file is part of ORB
##
## ORB is free software: you can redistribute it and/or modify it
## under the terms of the GNU General Public License as published by
## the Free Software Foundation, either version 3 of the License, or
## (at your option) any later version.
##
## ORB is distributed in the hope that it will be useful, but WITHOUT
## ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
## or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public
## License for more details.
##
## You should have received a copy of the GNU General Public License
## along with ORB.  If not, see <http://www.gnu.org/licenses/>.


import pylab as pl
import astropy.wcs
import matplotlib.cm
import matplotlib.colors
import numpy as np

def imshow(data, figsize=(15,15), perc=99, cmap='viridis', wcs=None, alpha=1, ncolors=None,
           vmin=None, vmax=None):
    """Convenient image plotting function

    :param figsize: size of the figure (same as pyplot.figure's figsize keyword)

    :param perc: percentile of the data distribution used to scale
      the colorbar. Can be a tuple (min, max) or a scalar in which
      case the min percentile will be 100-perc.

    :param cmap: colormap

    :param wcs: if a astropy.WCS instance show celestial coordinates,
      Else, pixel coordinates are shown.

    :param alpha: image opacity (if another image is displayed above)

    :param ncolors: if an integer is passed, the colorbar is
      discretized to this number of colors.

    :param vmin: min value used to scale the colorbar. If set the
      perc parameter is not used.

    :param vmax: max value used to scale the colorbar. If set the
      perc parameter is not used.
    """
    try:
        iter(perc)
    except Exception:
        perc = np.clip(float(perc), 50, 100)
        perc = 100-perc, perc

    else:
        if len(list(perc)) != 2:
            raise Exception('perc should be a tuple of len 2 or a single float')

    if vmin is None: vmin = np.nanpercentile(data, perc[0])
    if vmax is None: vmax = np.nanpercentile(data, perc[1])

    if ncolors is not None:
        cmap = getattr(matplotlib.cm, cmap)
        norm = matplotlib.colors.BoundaryNorm(np.linspace(vmin, vmax, ncolors),
                                              cmap.N, clip=True)
    else:
        norm = None

    fig = pl.figure(figsize=figsize)
    if wcs is not None:
        assert isinstance(wcs, astropy.wcs.WCS), 'wcs must be an astropy.wcs.WCS instance'
        
        ax = fig.add_subplot(111, projection=wcs)
        ax.coords[0].set_major_formatter('d.dd')
        ax.coords[1].set_major_formatter('d.dd')
    pl.imshow(data.T, vmin=vmin, vmax=vmax, cmap=cmap, origin='lower', alpha=alpha,norm=norm)
