#!/usr/bin/python
# *-* coding: utf-8 *-*
# Author: Thomas Martin <thomas.martin.1@ulaval.ca>
# File: spectrum.py

## Copyright (c) 2010-2016 Thomas Martin <thomas.martin.1@ulaval.ca>
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

import numpy as np
import math
from scipy import interpolate, optimize, special
import warnings
import time

import orb.constants
import orb.cutils
import orb.data as od

def create_nm_axis(n, step, order, corr=1.):
    """Create a regular wavelength axis in nm.

    :param n: Number of steps on the axis
    
    :param step: Step size in nm
    
    :param order: Folding order (cannot be 0)
    
    :param corr: (Optional) Coefficient of correction (default 1.)
    """
    
    nm_min = orb.cutils.get_nm_axis_min(int(n), float(step),
                                        int(order), corr=float(corr))
    if (order > 0): 
        nm_max = orb.cutils.get_nm_axis_max(int(n), float(step),
                                            int(order), corr=float(corr))
        return np.linspace(nm_min, nm_max, n, dtype=np.longdouble)
    else:
        raise Exception("order must be > 0")
    
def create_cm1_axis(n, step, order, corr=1.):
    """Create a regular wavenumber axis in cm-1.

    :param n: Number of steps on the axis
    
    :param step: Step size in nm
    
    :param order: Folding order
    
    :param corr: (Optional) Coefficient of correction (default 1.)
    """
    cm1_min = orb.cutils.get_cm1_axis_min(int(n), float(step),
                                          int(order), corr=float(corr))
    cm1_max = orb.cutils.get_cm1_axis_max(int(n), float(step),
                                          int(order), corr=float(corr))
    return np.linspace(cm1_min, cm1_max, n, dtype=np.longdouble) 
    
    
def create_nm_axis_ireg(n, step, order, corr=1.):
    """Create an irregular wavelength axis from the regular wavenumber
    axis in cm-1.

    :param n: Number of steps on the axis
    
    :param step: Step size in nm
    
    :param order: Folding order (must be > 0)
    
    :param corr: (Optional) Coefficient of correction (default 1.)
    """
    if order > 0:
        return (1. / create_cm1_axis(n, step, order, corr=corr) * 1e7)
    else:
        raise Exception("Order must be > 0")
        
    
def pix2nm(nm_axis, pix):
     """Convert a pixel position to a wavelength in nm given an axis
     in nm

     .. warning:: Slow because of interpolation : using
       fast_pix2w is much faster.

     :param nm_axis: Axis in nm
     
     :param pix: Pixel position
     """  
     f = interpolate.interp1d(np.arange(nm_axis.shape[0]), nm_axis,
                              bounds_error=False, fill_value=np.nan)
     return f(pix)
   

def nm2pix(nm_axis, nm):
     """Convert a wavelength in nm to a pixel position given an axis
     in nm

     .. warning:: Slow because of interpolation : using
       fast_w2pix is much faster.

     :param nm_axis: Axis in nm
     
     :param nm: Wavelength in nm
     """
     x = np.arange(nm_axis.shape[0])
     inverted = False
     if nm_axis[0] > nm_axis[-1]:
         nm_axis = np.copy(nm_axis[::-1])
         x = x[::-1]
         inverted = True
     f = interpolate.interp1d(nm_axis, x, bounds_error=False, fill_value=np.nan)
     if not inverted:
         return f(nm)
     else:
         return f(nm)[::-1]

def nm2cm1(nm):
    """Convert a wavelength in nm to a wavenumber in cm-1.

    :param nm: wavelength in nm
    """
    return 1e7 / np.array(nm).astype(float)

def cm12nm(cm1):
    """Convert a wavenumber in cm-1 to a wavelength in nm.

    :param cm1: wavenumber in cm-1
    """
    return 1e7 / np.array(cm1).astype(float)

def pix2cm1(cm1_axis, pix):
     """Convert a wavenumber in cm-1 to a pixel position given an axis
     in cm-1.

     :param cm1_axis: Axis in cm-1
     
     :param pix: Pixel position
     """
     f = interpolate.interp1d(np.arange(cm1_axis.shape[0]), cm1_axis,
                              bounds_error=False, fill_value=np.nan)

     return f(pix)
 
def cm12pix(cm1_axis, cm1):
     """Convert a wavenumber in cm-1 to a pixel position given an axis
     in cm-1.

     :param cm1_axis: Axis in cm-1
     
     :param cm1: Wavenumber in cm-1
     """
     f = interpolate.interp1d(cm1_axis, np.arange(cm1_axis.shape[0]),
                              bounds_error=False, fill_value=np.nan)
     return f(cm1)

def fwhm_nm2cm1(fwhm_nm, nm):
    """Convert a FWHM in nm to a FWHM in cm-1.
    
    The central wavelength in nm of the line must also be given

    :param fwhm_nm: FWHM in nm
    
    :param nm: Wavelength in nm where the FWHM is evaluated
    """
    return 1e7 * fwhm_nm / nm**2.

def fwhm_cm12nm(fwhm_cm1, cm1):
    """Convert a FWHM in cm-1 to a FWHM in nm.
    
    The central wavelength in cm-1 of the line must also be given

    :param fwhm_cm1: FWHM in cm-1
    
    :param cm1: Wavelength in cm-1 where the FWHM is evaluated
    """
    return 1e7 * fwhm_cm1 / cm1**2.

def line_shift(velocity, line, wavenumber=False):
    """Return the line shift given its velocity in nm or in cm-1.

    beta = v / c

    gamma = sqrt((1 + beta) / (1 - beta))

    lambda - lambda_0 = lambda_0  * (gamma - 1)

    :param velocity: Line velocity in km.s-1

    :param line: Wavelength/wavenumber of the line. Must be in cm-1 if
      wavenumber is True, must be in nm otherwise.

    :param wavenumber: (Optional) If True the result is returned in cm-1,
      else it is returned in nm.
    """
    is_data = od.isdata(velocity) or od.isdata(line)
    vel = (od.array(line, dtype=np.longdouble)
           * od.array(velocity, dtype=np.longdouble)
           / float(orb.constants.LIGHT_VEL_KMS))
    beta = od.array(velocity, dtype=np.longdouble) / float(orb.constants.LIGHT_VEL_KMS)
    gamma = od.sqrt((1. + beta) / (1. - beta))
    if wavenumber: 
        shift = od.array(line, dtype=np.longdouble) * (1. / gamma - 1.)
    else:
        shift = od.array(line, dtype=np.longdouble) * (gamma - 1.)
    if not is_data: shift = shift.dat
    return shift

def compute_line_fwhm(step_nb, step, order, apod_coeff=1., corr=1.,
                      wavenumber=False):
    """Return the expected FWHM (in nm or in cm-1) of a line given the
    observation parameters.

    :param step_nb: Number of steps from the zpd to the longest side
      of the interferogram.
    
    :param step: Step size in nm
    
    :param order: Folding order
    
    :param apod_coeff: (Optional) Apodization coefficient. 1. stands
      for no apodization and gives the FWHM of the central lobe of the
      sinc (default 1.)

    :param corr: (Optional) Coefficient of correction (default 1.)
    
    :param wavenumber: (Optional) If True the result is returned in cm-1,
      else it is returned in nm.
    """
    opd_max = step_nb * step / corr
    if not wavenumber:
        nm_axis = create_nm_axis(step_nb, step, order)
        nm_mean = (nm_axis[-1] + nm_axis[0])/2.
        return (nm_mean**2. * orb.constants.FWHM_SINC_COEFF
                / (2 * opd_max) * apod_coeff)
    else:
        return orb.constants.FWHM_SINC_COEFF / (2 * opd_max) * apod_coeff * 1e7
        
def compute_line_fwhm_pix(oversampling_ratio=1.):
    """Return the expected FWHM of an unapodized sinc line in pixels.

    :oversampling_ratio: Ratio of the real number of steps of the
      spectrum vs step_nb (must be > 1.) For a two sided interferogram
      the oversampling ratio is 2.
    """
    return orb.constants.FWHM_SINC_COEFF * oversampling_ratio
    
def compute_mean_shift(velocity, step_nb, step, order, wavenumber=False):
    """Return the mean shift at the central wavelength of the band
    defined by step and order parameters given its velocity in nm or
    in cm-1.

    :param velocity: Line velocity in km.s-1
    
    :param step_nb: Number of steps

    :param step: Step size in nm

    :param order: Folding order

    :param wavenumber: (Optional) If True the result is returned in cm-1,
      else it is returned in nm.
    """
    if not wavenumber:
        nm_axis = create_nm_axis(step_nb, step, order)
        mean = (nm_axis[-1] + nm_axis[0])/2.
    else:
        cm1_axis = create_cm1_axis(step_nb, step, order)
        mean = (cm1_axis[-1] + cm1_axis[0])/2.
        
    return line_shift(velocity, mean, wavenumber=wavenumber)
        
def compute_step_nb(resolution, step, order):
    """Return the number of steps on the longest side of the
    interferogram given the resolution and the observation
    parameters.

    :param resolution: Resolution
    
    :param step: Step size (in nm)
    
    :param order: Folding order
    """
    cm1_axis = create_cm1_axis(100, step, order)
    mean_sigma = (cm1_axis[-1] + cm1_axis[0])/2.
    return math.ceil(orb.constants.FWHM_SINC_COEFF
            * resolution
            / (2 * mean_sigma * step * 1e-7))

def compute_radial_velocity(line, rest_line, wavenumber=False):
    """
    Return radial velocity in km.s-1

    V [km.s-1] = c [km.s-1]* (Lambda^2 / Lambda_0^2 - 1) / (Lambda^2 / Lambda_0^2 + 1)

    :param line: Emission line wavelength/wavenumber (can be a numpy
      array)
    
    :param rest_line: Rest-frame wavelength/wavenumber (can be a numpy
      array but must have the same size as line)

    :param wavenumber: (Optional) If True the result is returned in cm-1,
      else it is returned in nm.
    """
    if (not isinstance(line, np.ndarray)
        and not isinstance(line, od.Data)):
        line = np.array(line, dtype=np.longdouble)
    if (not isinstance(rest_line, np.ndarray)
        and not isinstance(line, od.Data)):
        rest_line = np.array(rest_line, dtype=np.longdouble)
    if line.dtype != np.longdouble:
        line = line.astype(np.longdouble)
    if rest_line.dtype != np.longdouble:
        rest_line = rest_line.astype(np.longdouble)

    if wavenumber:
        ratio = (rest_line / line)**2.
    else:
        ratio = (line / rest_line)**2.
    return orb.constants.LIGHT_VEL_KMS * (ratio - 1) / (ratio + 1)
    

def lorentzian1d(x, h, a, dx, fwhm):
    """Return a 1D lorentzian
    :param x: Array giving the positions where the function is evaluated
    :param h: Height
    :param a: Amplitude
    :param dx: Position of the center
    :param fwhm: FWHM
    """
    return h + (a / (1. + ((x-dx)/(fwhm/2.))**2.))

def sinc1d(x, h, a, dx, fwhm):
    """Return a 1D sinc 
    :param x: Array giving the positions where the function is evaluated
    :param h: Height
    :param a: Amplitude
    :param dx: Position of the center
    :param fwhm: FWHM
    """
    if not isinstance(x, np.ndarray):
        x = np.array(x)
    if x.dtype != float:
        x = x.astype(float)
    return orb.cutils.sinc1d(
        x, float(h), float(a), float(dx), float(fwhm))

def gaussian1d(x,h,a,dx,fwhm):
    """Return a 1D gaussian given a set of parameters.

    :param x: Array giving the positions where the gaussian is evaluated
    :param h: Height
    :param a: Amplitude
    :param dx: Position of the center
    :param fwhm: FWHM, :math:`\\text{FWHM} = \\text{Width} \\times 2 \\sqrt{2 \\ln 2}`
    """
    if not isinstance(x, np.ndarray):
        x = np.array(x)
    if x.dtype != float:
        x = x.astype(float)
    return orb.cutils.gaussian1d(
        x, float(h), float(a), float(dx), float(fwhm))
                        
def sincgauss1d(x, h, a, dx, fwhm, sigma):
    """Return a 1D sinc convoluted with a gaussian of parameter sigma.

    If sigma == 0 returns a pure sinc.

    :param x: 1D array of float64 giving the positions where the
      sinc is evaluated
    
    :param h: Height
    :param a: Amplitude
    :param dx: Position of the center
    :param fwhm: FWHM of the sinc
    :param sigma: Sigma of the gaussian.
    """
    if sigma / fwhm < 1e-10:
        return sinc1d(x, h, a, dx, fwhm)

    width = abs(fwhm) / orb.constants.FWHM_SINC_COEFF
    width /= math.pi ###
    a_ = sigma / math.sqrt(2) / width
    b_ = ((x - dx) / math.sqrt(2) / sigma).astype(float)

    dawson1 = special.dawsn(1j*a_ + b_) * np.exp(2.*1j*a_*b_)
    dawson2 = special.dawsn(1j*a_ - b_) * np.exp(-2.*1j*a_*b_)
    dawson3 = special.dawsn(1j*a_)
    
    return h + (a/2. * (dawson1 + dawson2)/dawson3).real


def gaussian1d_flux(a, fwhm):
    """Compute flux of a 1D Gaussian.

    :param a: Amplitude
    :param fwhm: FWHM
    """
    width = fwhm / orb.constants.FWHM_COEFF
    return od.abs(a * math.sqrt(2*math.pi) * width)

def sinc1d_flux(a, fwhm):
    """Compute flux of a 1D sinc.

    :param a: Amplitude
    :param fwhm: FWHM
    """
    width = fwhm / orb.constants.FWHM_SINC_COEFF
    return od.abs(a * width)

def sinc21d_flux(a,fwhm):
    """Compute flux of a 1D sinc2.
    THIS IS BOGUS WITH CURRENT DEFINITION OF SINC2 MODEL
    :param a: Amplitude
    :param fwhm: FWHM
    """
    width = fwhm / orb.constants.FWHM_SINC_COEFF
    return od.abs(a*fwhm)
    
def sincgauss1d_flux(a, fwhm, sigma):
    """Compute flux of a 1D sinc convoluted with a Gaussian of
    parameter sigma.

    :param a: Amplitude
    :param fwhm: FWHM of the sinc
    :param sigma: Sigma of the gaussian
    """
    width = fwhm / orb.constants.FWHM_SINC_COEFF
    width /= math.pi
    return od.abs((a * 1j * math.pi / math.sqrt(2.) * sigma
                  * od.exp(sigma**2./2./width**2.)
                  / (od.dawsn(1j * sigma / (math.sqrt(2) * width)))).real)
   
def fast_w2pix(w, axis_min, axis_step):
    """Fast conversion of wavelength/wavenumber to pixel

    :param w: wavelength/wavenumber
    
    :param axis_min: min axis wavelength/wavenumber
    
    :param axis_step: axis step size in wavelength/wavenumber
    """
    return np.abs(w - axis_min) / axis_step

def fast_pix2w(pix, axis_min, axis_step):
    """Fast conversion of pixel to wavelength/wavenumber

    :param pix: position along axis in pixels
    
    :param axis_min: min axis wavelength/wavenumber
    
    :param axis_step: axis step size in wavelength/wavenumber
    """
    return pix * axis_step + axis_min

def thermal_broadening_kms(wl, aw, T):
    """
    Return the width of the line due to thermal broadening in km/s.

    Equation can be refered to Harwit (Astrophysical concepts) but his
    definition gives the HWHM (Half-Width at Half-Maximum).
    
    :param wl: Wavelength of the line (in nm)
    :param aw: Atomic weight of the emitting atom
    :param T: Temperature in K
    """
    E = aw * orb.constants.ATOMIC_MASS * (orb.constants.LIGHT_VEL_KMS * 1e5) **2.
    width = wl * np.sqrt(orb.constants.K_BOLTZMANN * T / E) # nm
    return orb.constants.LIGHT_VEL_KMS *  width / wl # kms

def phase_shift_cm1_axis(step_nb, step, order, nm_laser_obs, nm_laser):
    """Compute phase shift on a given cm1 axis

    :param step_nb: Number of steps
    :param step: Step size in nm
    :param order: Folding order
    :param nm_laser_obs: Observed calibration laser wavelength (in nm)
    :param nm_laser: Calibration laser wavelength (in nm)
    """
    corr = nm_laser_obs / nm_laser
    cm1_min_corr = orb.cutils.get_cm1_axis_min(int(step_nb), float(step),
                                               int(order), corr=float(corr))
    cm1_min_base = orb.cutils.get_cm1_axis_min(int(step_nb), float(step),
                                               int(order))
    cm1_axis_step =  orb.cutils.get_cm1_axis_step(int(step_nb),
                                                  float(step),
                                                  corr=float(corr))
    delta_cm1 = cm1_min_corr - cm1_min_base
    delta_x = - (delta_cm1 / cm1_axis_step)
    return delta_x
