#!/usr/bin/python
# *-* coding: utf-8 *-*
# Author: Thomas Martin <thomas.martin.1@ulaval.ca>
# File: astrometry.py

## Copyright (c) 2010-2017 Thomas Martin <thomas.martin.1@ulaval.ca>
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

import logging
from scipy import optimize, interpolate, signal
import math
import bottleneck as bn
import numpy as np
import warnings
import astropy.wcs as pywcs
import pandas

import orb.cutils
import orb.utils.stats
import orb.utils.image
import orb.utils.vector
import orb.utils.parallel
import orb.utils.misc

import copy


##################################################
#### CLASS PSF ###################################
##################################################


class PSF(object):
    """General class of inheritance for point spread functions (PSFs)
    """
    params = None

    def __repr__(self):
        return(str(self.params))

    def array2d(self, nx, ny):
        """Return a 2D profile given the size of the returned
        array.
        
        :param nx: Length of the returned array along x axis
        :param ny: Length of the returned array along y axis
        """
        return self.varray2d(int(nx), int(ny))
    
    def varray2d(self, nx, ny):
        """Return a vectorized 2D profile given the size of the returned
        array.
        
        :param nx: Length of the returned array along x axis
        :param ny: Length of the returned array along y axis
        """
        return np.fromfunction(
            np.vectorize(self.psf2d), (int(nx), int(ny)))

    

##################################################
#### CLASS Moffat ################################
##################################################


class Moffat(PSF):
    """Class implementing the Moffat profile.

    This profile is useful to fit stars on CCD arrays.

    .. note:: The Moffat profile has been first proposed by Moffat
      (1969) A&A. The exact form of the equation used has been derived
      from Trujillo et al. (2001) MNRAS, 977. The PSF:

      :math:`f(x,y) = H + A \\times [1+(\\frac{r}{\\alpha})^2]^{-\\beta}`

      with,
      :math:`\\alpha = \\frac{\\text{FWHM}}{2\\sqrt{2^{1/\\beta} - 1}}`

      and,
      :math:`r = (x - dx)^2 + (y - dy)^2`
    
      The total flux F under the 2D profile is thus:
      :math:`F = A \\times \\frac{\\pi \\alpha^2}{\\beta - 1}`
    """

    input_params = list(['height', 'amplitude', 'x', 'y', 'fwhm', 'beta'])
    """Keys of the input parameters"""
    
    params = dict()
    """dictionary containing the parameters of the profile"""
    
    alpha = None # Alpha: coefficient defined from beta and FWHM

    def __init__(self, params):
        """Init Moffat profile parameters

        :param params: Input parameters of the Moffat profile. Input
          parameters can be given as a dictionary providing {'height',
          'amplitude', 'x', 'y', 'fwhm', 'beta'} or an array of 6
          elements stored in this order: ['height', 'amplitude', 'x',
          'y', 'fwhm', 'beta']
        """
        MAX_BETA = 30.
        self.params = dict()
        
        if isinstance(params, dict):
            if (set([key for key in params.iterkeys()])
                & set(self.input_params) == set(self.input_params)):
                self.params['height'] = float(params['height'])
                self.params['amplitude'] = float(params['amplitude'])
                self.params['x'] = float(params['x'])
                self.params['y'] = float(params['y'])
                self.params['fwhm'] = abs(float(params['fwhm']))
                self.params['beta'] = float(params['beta'])
            else:
                raise ValueError("Input dictionary is not valid. You must provide a dictionary containing all those keys : %s"%str(self.input_params))

        elif (np.size(params) == np.size(self.input_params)):
            self.params['height'] = float(params[0])
            self.params['amplitude'] = float(params[1])
            self.params['x'] = float(params[2])
            self.params['y'] = float(params[3])
            self.params['fwhm'] = abs(float(params[4]))
            self.params['beta'] = float(params[5])

        else:
            raise ValueError('Invalid input parameters')


        if self.params['beta'] > MAX_BETA: self.params['beta'] = MAX_BETA

        # Computation of alpha
        # Beta must not be negative or too near 0
        if (self.params['beta'] > .1):
            self.alpha = (self.params['fwhm']
                          / (2. * np.sqrt(2.**(1. / self.params['beta']) - 1.)))
        else:
            self.alpha = np.nan

        self.params['flux'] = self.flux()

        # 1-D PSF function
        self.psf = lambda r: (
            self.params['height'] + self.params['amplitude']
            * (1. + (r/self.alpha)**2.)**(-self.params['beta']))
        
        # 2-D PSF function
        self.psf2d = lambda x, y: (
            self.psf(np.sqrt((x - self.params['x'])**2.
                             + (y - self.params['y'])**2.)))
        

    def flux(self):
        """Return the total flux under the 2D profile.
        """
        if self.params['beta'] != 1.:
            return (self.params['amplitude']
                    * ((math.pi * self.alpha**2.)
                       / (self.params['beta'] - 1.)))
        else:
            return np.nan

    def flux_error(self, amplitude_err, width_err):
        """Return flux error.
        
        :param amplitude_err: estimation of the amplitude error
        
        :param width_err: estimation of the width error

        .. warning:: Not implemented yet!
        """
        return np.nan

    def array2d(self, nx, ny):
        """Return a 2D profile given the size of the returned
        array.
        
        :param nx: Length of the returned array along x axis
        :param ny: Length of the returned array along y axis
        """
        return np.array(orb.cutils.moffat_array2d(
            float(self.params['height']), float(self.params['amplitude']),
            float(self.params['x']), float(self.params['y']),
            float(self.params['fwhm']), self.params['beta'], int(nx), int(ny)))
    
##################################################
#### CLASS Gaussian ##############################
##################################################


class Gaussian(PSF):
    """Class implementing the gaussian profile

    .. note:: The Gaussian profile used here is:
      :math:`f(x,y) = H + A \\times \exp(\\frac{-r^2}{2 W^2})`

      and,
      :math:`r = (x - dx)^2 + (y - dy)^2`
      
      The total flux F under the 2D profile is:
      :math:`F = 2 \\pi A W^2`
    
    """


    input_params = list(['height', 'amplitude', 'x', 'y', 'fwhm'])
    """Keys of the input parameters"""
    
    params = dict()
    """dictionary containing the parameters of the profile"""
    
    width = None # Width = FWHM / abs(2.*sqrt(2. * log(2.)))


    def __init__(self, params):
        """Init Gaussian profile parameters

        :param params: Input parameters of the Gaussian profile. Input
          parameters can be given as a dictionary providing {'height',
          'amplitude', 'x', 'y', 'fwhm'} or an array of 5
          elements stored in this order: ['height', 'amplitude', 'x',
          'y', 'fwhm']
        """
        
        self.params = dict()
        if isinstance(params, dict):
            if (set([key for key in params.iterkeys()])
                & set(self.input_params) == set(self.input_params)):
                self.params['height'] = float(params['height'])
                self.params['amplitude'] = float(params['amplitude'])
                self.params['x'] = float(params['x'])
                self.params['y'] = float(params['y'])
                self.params['fwhm'] = abs(float(params['fwhm']))
            else:
                raise ValueError("Input dictionary is not valid. You must provide a dictionary containing all those keys : %s"%str(self.input_params))

        elif (np.size(params) == np.size(self.input_params)):
            self.params['height'] = float(params[0])
            self.params['amplitude'] = float(params[1])
            self.params['x'] = float(params[2])
            self.params['y'] = float(params[3])
            self.params['fwhm'] =  abs(float(params[4]))

        else:
            raise ValueError('Invalid input parameters')


        self.width = self.params['fwhm'] / abs(2.*math.sqrt(2. * math.log(2.)))
        self.params['flux'] = self.flux()


        # 1-D PSF function
        self.psf = lambda r: (
            self.params['height'] + self.params['amplitude']
            * np.exp(-(r)**2./(2.*self.width**2.)))
        
        # 2-D PSF function
        self.psf2d = lambda x, y: (
            self.psf(math.sqrt((x-self.params['x'])**2.
                               +(y-self.params['y'])**2.)))
        

    def flux(self):
        """Return the total flux under the 2D profile.
        
        The total flux F under a 2D profile is :
        :math:`F = 2 \\pi A W^2`
        
        .. note:: Under a 1d profile the flux is :math:`F = \\sqrt{2\\pi}A W`
        """
        return 2. * self.params['amplitude'] * (self.width)**2 * math.pi

    def flux_error(self, amplitude_err, width_err):
        """Return flux error.
        
        :param amplitude_err: estimation of the amplitude error
        
        :param width_err: estimation of the width error
        """
        return self.flux() * math.sqrt(
            (amplitude_err / self.params['amplitude'])**2.
            + 2. * (width_err / self.width)**2.)
    
    def array2d(self, nx, ny):
        """Return a 2D profile given the size of the returned
        array.
        
        :param nx: Length of the returned array along x axis
        :param ny: Length of the returned array along y axis
        """
        return np.array(orb.cutils.gaussian_array2d(float(self.params['height']),
                                                float(self.params['amplitude']),
                                                float(self.params['x']),
                                                float(self.params['y']),
                                                float(self.params['fwhm']),
                                                int(nx), int(ny)))

def mag(flux):
    """Return the instrumental magnitude of a given flux (magnitude 0
      is set to 1 e-)

    :param flux: Flux in e-
    """
    return np.where(flux > 0., -2.5 * np.log10(flux), np.nan)

def guess(star_box, pos=None, height=None, precise_pos=False):
    """Return an estimation of the star parameters.

    :param star_box: Sub-part of an image surrounding a star. The
      center of the star must be placed near the center of the
      box. The dimensions of the box must be greater than 3 times
      the FWHM of the star.

    :param pos: (Optional) Position guess as a tuple (x,y). Used to
      estimate amplitude (default None).

    :param height: (Optional) Guess of the background level. Used to
      estimate amplitude (default None).

    :param precise_pos: (Optional) If True, position is estimated from
      the marginal distribution of the PSF. Return a far better
      estimation if and only if the star is well centered in the box,
      i.e. if and only if the position of the star is already
      known. This can lead to errors when trying to find the star in
      the box, in this case precise_pos must be set to False (default
      False).

    :return: [height,amplitude,x,y,width]
    """
    if pos is not None:
        x_guess = pos[0]
        y_guess = pos[1]
    else:
        # Estimation of the position from the marginal distribution of the psf
        # [e.g. Howell 2006]
        if precise_pos:
            box_dimx = star_box.shape[0]
            box_dimy = star_box.shape[1]
            Ii = np.sum(star_box, axis=1)
            Jj = np.sum(star_box, axis=0)
            I = Ii - np.mean(Ii)
            nzi = np.nonzero(I > 0)
            J = Jj - np.mean(Jj)
            nzj = np.nonzero(J > 0)
            x_guess = np.sum((I[nzi])*np.arange(box_dimx)[nzi])/np.sum(I[nzi])
            y_guess = np.sum((J[nzj])*np.arange(box_dimy)[nzj])/np.sum(J[nzj])
            if np.isnan(x_guess):
                x_guess = np.argmax(np.sum(star_box, axis=1))
            if np.isnan(y_guess):
                y_guess = np.argmax(np.sum(star_box, axis=0))
        else:
            x_guess = np.argmax(np.sum(star_box, axis=1))
            y_guess = np.argmax(np.sum(star_box, axis=0))
            
    if height is not None:
        h_guess = height
    else:
        h_guess = sky_background_level(star_box)
        
    a_guess = star_box[int(x_guess), int(y_guess)] - h_guess
    fwhm_guess = float(min(star_box.shape)) * 0.2
    
    return [h_guess,a_guess,x_guess,y_guess,fwhm_guess]


def fit_star(star_box, profile_name='gaussian', fwhm_pix=None,
             amp=None, beta=3.5, height=None, pos=None,
             fix_height=False, fix_amp=False, fix_beta=True,
             fix_fwhm=False, fix_pos=False,
             fit_tol=1e-3, check=True, fwhm_min=0.5,
             check_reject=False, ron=10., dcl=0.,
             estimate_local_noise=True, precise_guess=False,
             saturation=None):

    """Fit a single star

    :param star_box: The box where the star has to be fitted.

    :param profile_name: (Optional) Name of the PSF profile to use to
      fit stars. May be 'gaussian' or 'moffat' (default 'gaussian').

    :param amp: (Optional) Amplitude guess, replace the value of the
      automatic estimation (default None).

    :param fwhm_pix: (Optional) Estimate of the FWHM in pixels. If
      None given FWHM is estimated to half the box size (default
      None).
      
    :param beta: (Optional) Beta parameter of the moffat psf. Used
      only if the fitted profile is a Moffat psf (default 3.5).

    :param height: (Optional) Height guess, replace the value of the
      automatic estimation (default None).

    :param pos: (Optional) Position guess as a tuple (x,y), replace
      the value of the automatic estimation (default None).

    :param fix_amp: (Optional) Fix amplitude parameter to its
      estimation (default False)

    :param fix_height: (Optional) Fix height parameter to its
      estimation (default False)

    :param fix_beta: (Optional) Fix beta to the given value (default
      True).

    :param fix_fwhm: (Optional) Fix FWHM to its estimation (default
      False).
      
    :param fix_pos: (Optional) Fix position parameters (x,y) at their
      estimated value (default False).

    :param fit_tol: (Optional) Tolerance on the paramaters fit (the
      lower the better but the longer too) (default 1e-2).

    :param check: (Optional) If True, check fit results for oddities
      (default True).

    :param fwhm_min: (Optional) Minimum valid FWHM [in pixel] of the
      fitted star (default 0.5)

    :param check_reject: (Optional) [Debug] If True, print the reason
      why a fit is rejected (default False).

    :param ron: (Optional) Readout noise in ADU/pixel (default
      10.). estimate_local_noise must be set to False for this noise
      to be taken into account.

    :param dcl: (Optional) Dark current level in ADU/pixel (default
      0.). estimate_local_noise must be set to False for this noise to
      be taken into account.

    :param estimate_local_noise: (Optional) If True, the level of
      noise is computed from the background pixels around the
      stars. ron and dcl are thus not used (default True).

    :param precise_guess: (Optional) If True, the fit guess will be
      more precise but this can lead to errors if the stars positions
      are not already well known (default False).

    :param saturation: (Optional) If not None, all pixels above the
      saturation level are removed from the fit (default None).
    """
    def get_background_noise(data, fwhm, posx, posy):
        FWHM_SKY_COEFF = 1.5
        SUB_DIV = 10
        # background noise is computed from the std of 'sky'
        # pixels around the object. The poisson noise is removed
        # because it is added when the real sigma is calculated.
        if fwhm is not None:
            # if FWHM is known sky pixels are considered to be at more
            # than 3 sigma of the guessed star position
            S_sky = orb.cutils.surface_value(
                data.shape[0], data.shape[1],
                posx, posy, FWHM_SKY_COEFF * fwhm,
                max(data.shape[0], data.shape[1]), SUB_DIV)
            sky_pixels = data * S_sky
            sky_pixels = sky_pixels[np.nonzero(sky_pixels)]
        else:
            # else a sigma cut is made over the pixels to remove too
            # high values
            sky_pixels = orb.utils.stats.sigmacut(data, sigma=4.)

        mean_sky = orb.utils.stats.robust_mean(orb.utils.stats.sigmacut(
            sky_pixels, sigma=4.))
        if mean_sky < 0: mean_sky = 0
        background_noise = (
            orb.utils.stats.robust_std(sky_pixels)
            - np.sqrt(mean_sky))
   
        return background_noise
        
    def sigma(data, ron, dcl):
        # guessing sigma as sqrt(photon noise + readout noise^2 + dark
        # current level)
        return np.sqrt(abs(data) + (ron)**2. + dcl)
        
    def diff(free_p, free_i, fixed_p, profile, data, sig, saturation):
        data_dimx = data.shape[0]
        data_dimy = data.shape[1]
        params = fixed_p
        params[free_i] = free_p
        prof = profile(params)
        model = prof.array2d(data_dimx, data_dimy)
        result = (data - model) / sig
        if saturation is not None:
            result[np.nonzero(data >= saturation)] = np.nan
        result = result[np.nonzero(~np.isnan(result))]
        result = result[np.nonzero(~np.isinf(result))]
        return result.flatten()


    star_box = star_box.astype(float)
    if np.any(np.isnan(star_box)):
        return []
    if np.all(star_box == 0):
        return []

    # correct star_box level if the background level is < 0
    if np.median(star_box) < 0:
        level_correction = np.min(star_box)
        star_box -= level_correction
    else:
        level_correction = 0.

    # Get parameters guess
    guess_params = guess(star_box, pos=pos, height=height,
                         precise_pos=precise_guess)

    # Guessed params are replaced by given values (if not None)
    if height is not None:
        guess_params[0] = height
    if amp is not None:
        guess_params[1] = amp
    if fwhm_pix is not None:
        guess_params[4] = fwhm_pix
    if pos is not None:
        if np.size(pos) == 2:
            guess_params[2] = pos[0]
            guess_params[3] = pos[1]
        else:
            raise ValueError('Bad position guess : must be a tuple (x,y)')

    # local estimate of the noise
    if estimate_local_noise:
        ron = get_background_noise(star_box, fwhm_pix,
                                   guess_params[2], guess_params[3])
        dcl = 0.
        
    profile = get_profile(profile_name)

    if profile_name == 'moffat':
        guess_params = np.concatenate((guess_params, [beta]))
        
    guess_params = np.array(guess_params, dtype=float)

    fixed_params = np.copy(guess_params)
    masked_params = np.ones_like(guess_params, dtype=np.bool)
    if fix_height:
        masked_params[0] = False
    if fix_amp:
        masked_params[1] = False
    if fix_pos:
        masked_params[2] = False
        masked_params[3] = False
    if fix_fwhm:
        masked_params[4] = False
    if fix_beta and profile_name == 'moffat':
        masked_params[5] = False
    

    free_params = guess_params[np.nonzero(masked_params)]
    free_index = np.arange(guess_params.shape[0])[np.nonzero(masked_params)]
    fixed_params[np.nonzero(masked_params)] = np.nan

    try:
        fit_params = optimize.leastsq(diff, free_params,
                                      args=(free_index, fixed_params,
                                            profile, star_box, sigma(
                                                star_box, ron, dcl),
                                            saturation),
                                      maxfev=100, full_output=True,
                                      xtol=fit_tol)
    except Exception, e:
        warnings.warn('fit_star leastsq exception: {}'.format(e))
        return []
    
    if fit_params[-1] <= 4:
        fixed_params[free_index] = fit_params[0]
        cov_x = fit_params[1]
        fit_params = profile(fixed_params).params
        fit_params['fwhm_pix'] = fit_params['fwhm']
        
        # Check fit params for oddities
        if check:
            box_size = min(star_box.shape)
            if not fix_fwhm:
                if fit_params['fwhm_pix'] < fwhm_min:
                    if check_reject: logging.info('FWHM < fwhm_min')
                    return []
                if fit_params['fwhm_pix'] > box_size:
                    if check_reject: logging.info('FWHM > box_size')
                    return []
            if not fix_pos:
                if abs(fit_params['x'] - guess_params[2]) > box_size/2.:
                    if check_reject: logging.info('DX > box_size / 2')
                    return []
                if abs(fit_params['y'] - guess_params[3]) > box_size/2.:
                    if check_reject: logging.info('DY > box_size / 2')
                    return []
            if not fix_amp:
                if fit_params['amplitude'] < 0.:
                    if check_reject: logging.info('AMP < 0')
                    return []
            if not fix_amp and not fix_height:
                if ((fit_params['amplitude'] + fit_params['height']
                     - np.min(star_box))
                    < ((np.max(star_box) - np.min(star_box)) * 0.5)):
                    if check_reject: logging.info('AMP + HEI < 0.5 * max')
                    return []
                if ((fit_params['height'] + fit_params['amplitude']
                     - np.min(star_box))
                    < (np.median(star_box) - np.min(star_box))):
                    if check_reject: logging.info('AMP + HEI < median')
                    return []
        
        # reduced chi-square
        fit_params['chi-square'] = np.sum(
            diff([],[], fixed_params, profile, star_box,
                 sigma(star_box, ron, dcl), saturation)**2.)
            
        fit_params['reduced-chi-square'] = (
            fit_params['chi-square']
            / (np.size(star_box) - np.size(free_params)))

        # restore level correction:
        fit_params['height'] += level_correction
        fit_params['amplitude'] += level_correction

        # SNR estimation (from Mighell, MNRAS 361,3 (2005))
        S = fit_params['fwhm_pix']/(2. * math.sqrt(math.log(4)))
        Beta = 4. * math.pi * (S**2.)
        N = np.size(star_box)
        flux = fit_params['flux']
        background_noise = (math.sqrt(abs(fit_params['height'])
                                      + (ron)**2. + dcl))
        SNR = (flux / np.sqrt(
            flux + Beta * (1. + math.sqrt(Beta/N))**2.
            * (background_noise**2.)))
        fit_params['snr'] = SNR
        
        # error estimation
        fit_params['height_err'] = 0.
        fit_params['amplitude_err'] = 0.
        fit_params['x_err'] = 0.
        fit_params['y_err'] = 0.
        fit_params['fwhm_err'] = 0.
        if profile_name == 'moffat':
            fit_params['beta_err'] = 0.
        fit_params['flux_err'] = 0.

        if cov_x is not None:
            cov_x *= fit_params['reduced-chi-square']
            for ip in range(len(free_index)):
                err = math.sqrt(abs(cov_x[ip,ip]))
                if free_index[ip] == 0:
                    fit_params['height_err'] = err
                elif free_index[ip] == 1:
                    fit_params['amplitude_err'] = err
                elif free_index[ip] == 2:
                    fit_params['x_err'] = err
                elif free_index[ip] == 3:
                    fit_params['y_err'] = err
                elif free_index[ip] == 4:
                    fit_params['fwhm_err'] = err
                elif free_index[ip] == 5 and profile_name == 'moffat':
                    fit_params['beta_err'] = err
            fit_params['flux_err'] = profile(fixed_params).flux_error(
                fit_params['amplitude_err'],
                fit_params['fwhm_err']/(2. * math.sqrt(math.log(4))))
        else:
            return []
        
        return fit_params
        
    else:
        return []

def aperture_photometry(star_box, fwhm_guess, background_guess=None,
                        background_guess_err=0.,
                        aper_coeff=3., warn=True, x_guess=None,
                        y_guess=None, return_surfaces=False,
                        aperture_surface=None, annulus_surface=None):
    """Return the aperture photometry of a star centered in a star box.

    :param star_box: Star box

    :param fwhm_guess: Guessed FWHM. Used to get the aperture radius.

    :param background_guess: (Optional) If not None, this guess is
      used instead of the background determination in an annulus
      around the star (default None).

    :param background_guess_err: (Optional) Error on the background
      guess. Used to compute the aperture photometry error (default 0.).

    :param aper_coeff: (Optional) Aperture coefficient. The aperture
      radius is Rap = aper_coeff * FWHM. Better when between 1.5 to
      reduce the variation of the collected photons with varying FWHM
      and 3. to account for the flux in the wings (default 3., better
      for Moffat stars with a high SNR).

    :param warn: (Optional) If True, print a warning when the background cannot
      be well estimated (default True).

    :param x_guess: (Optional) position of the star along x axis. If
      None, star is assumed to lie at the very center of the frame
      (default None).

    :param y_guess: (Optional) position of the star along y axis. If
      None, star is assumed to lie at the very center of the frame
      (default None).

    :param return_surfaces: (Optional) If True returns also the
      aperture_surface and annulus_surface computed. Useful if
      multiple stars with the same FWHM must be done (default False).

    :param aperture_surface: (Optional) Pre-computed
      aperture_surface. Accelerate the process for multiple stars with
      the same FWHM but must be used with caution. aper_coeff is of no
      use if aperture_surface if given (default None). See
      :py:meth:`orb.utils.astrometry.multi_aperture_photometry`.

    :param annulus_surface: (Optional) Pre-computed
      annulus_surface. Accelerate the process for multiple stars with
      the same FWHM but must be used with caution. aper_coeff is of no
      use if annulus_surface if given (default None). See
      :py:meth:`orb.utils.astrometry.multi_aperture_photometry`.

    :return: A Tuple (flux, flux_error, aperture surface,
      bad_estimation_flag). If the estimation is bad,
      bad_estimation_flat is set to 1, else it is set to 0.
    
    .. note:: Best aperture for maximum S/N: 1. FWHM (Howell 1989,
      Howell 1992). But that works only when the PSF is well sampled
      which is not always the case so a higher aperture coefficient
      may be better. More over, to get exact photometry the result
      must be corrected by aperture growth curve for the 'missing
      light'. A coefficient of 1.27 FWHM corresponds to 3 sigma and
      collects more than 99% of the light if the star is a pure
      Gaussian. A coefficient of 3 for Moffat stars reduces the
      variations of the proportion of collected photons when the FWHM
      is changing and seems to be the best.

    .. note:: Best radius for sky background annulus is determined
      from this rule of thumb: The number of pixels to estimate the
      background must be al least 3 times the number of pixel in the
      aperture (Merline & Howell 1995). Choosing the aperture radius
      coefficient(Cap) as Rap = Cap * FWHM and the inner radius
      coefficient (Cin) as Rin = Cin * FWHM, gives the outer radius
      coefficient (Cout): Cout = sqrt(3*Cap^2 + Cin^2)

    .. warning:: The star MUST be at the center (+/- 1 pixel) of the
      star box.

    .. seealso:: :py:meth:`orb.utils.astrometry.multi_aperture_photometry`
    """
    MIN_APER_SIZE = 0.5 # Minimum warning flux coefficient in the
                        # aperture
    
    C_AP = aper_coeff # Aperture coefficient
    
    C_IN = C_AP + 1. # Inner radius coefficient of the bckg annulus
    
    MIN_BACK_COEFF = 5. # Minimum percentage of the pixels in the
                        # annulus to estimate the background
                        
    SUR_VAL_COEFF = 10 # Number of pixel division to estimate the
                       # surface value

    # Outer radius coefficient of the annulus
    C_OUT = math.sqrt((MIN_BACK_COEFF*C_AP**2.) + C_IN**2.)
    
    bad = 0        
    box_dimx = star_box.shape[0]
    box_dimy = star_box.shape[1]
    if x_guess is None:
        x_guess = box_dimx / 2. - 0.5
    if y_guess is None:
        y_guess = box_dimy / 2. - 0.5
                                     
    # Aperture radius
    aper_rmax = C_AP * fwhm_guess

    # Get approximate pixels surface value of the pixels for the aperture
    if aperture_surface is None or aperture_surface.shape != (box_dimx, box_dimy):
        aperture_surface = orb.cutils.surface_value(
            box_dimx, box_dimy,
            x_guess, y_guess,
            0., aper_rmax, SUR_VAL_COEFF)
    # saved for clean output if return_surfaces is True
    base_aperture_surface = np.copy(aperture_surface) 
    
    aperture_surface[np.nonzero(np.isnan(star_box))] = 0.
    aperture = star_box * aperture_surface
    total_aperture = np.nansum(aperture)
    
    # compute number of nans
    aperture[np.nonzero(aperture_surface == 0.)] = 0.
    aperture_nan_nb = np.sum(np.isnan(aperture))
    
    
    if np.nansum(aperture_surface) < MIN_APER_SIZE:
        if warn:
            warnings.warn('Not enough pixels in the aperture')
        return np.nan, np.nan, np.nan, np.nan, np.nan, np.nan
    
    # Estimation of the background
    if background_guess is None:
        ann_rmin = math.floor(C_IN * fwhm_guess) + 0.5

        # C_OUT definition just does not work well at small radii, so the
        # outer radius has to be enlarged until we have a good ratio of
        # background counts
        ann_rmax = math.ceil(C_OUT * fwhm_guess) + 1
        not_enough = True
        while not_enough:
            if annulus_surface is None or annulus_surface.shape != (box_dimx, box_dimy):
                annulus_surface = np.copy(orb.cutils.surface_value(
                    box_dimx, box_dimy,
                    x_guess, y_guess,
                    ann_rmin, ann_rmax,
                    SUR_VAL_COEFF))
            # saved for clean output if return_surfaces is True
            base_annulus_surface= np.copy(annulus_surface)
            
            annulus_surface[np.nonzero(annulus_surface < 1.)] = 0. # no partial pixels are used
       
            if (np.sum(annulus_surface) >
                float(MIN_BACK_COEFF) *  np.sum(aperture_surface)):
                not_enough = False
            elif ann_rmax >= min(box_dimx, box_dimy) / 2.:
                not_enough = False
            else:
                ann_rmax += 0.5
                annulus_surface = None

        # background in counts / pixel
        if (np.sum(annulus_surface) >
            float(MIN_BACK_COEFF) *  np.nansum(aperture_surface)):
            background_pixels = star_box[np.nonzero(annulus_surface)]
            # background level is computed from the mode of the sky
            # pixels distribution
            background, background_err = sky_background_level(
                background_pixels, return_error=True)
            
        else:
            background_pixels = orb.utils.stats.sigmacut(star_box)
            background = orb.utils.stats.robust_mean(background_pixels)
            background_err = (orb.utils.stats.robust_std(background_pixels)
                              / math.sqrt(np.size(background_pixels)))
            
            if warn:
                warnings.warn('Estimation of the background might be bad')
                bad = 1
    else:
        background = background_guess
        background_err = background_guess_err

    aperture_flux = total_aperture - (background *  np.nansum(aperture_surface))
    aperture_flux_error = background_err * np.nansum(aperture_surface)

    returns = (aperture_flux, aperture_flux_error,
               np.nansum(aperture_surface), bad,
               background, background_err)
    if not return_surfaces:
        return returns
    else:
        return returns, base_aperture_surface, base_annulus_surface

def detect_fwhm_in_frame(frame, star_list, fwhm_guess_pix):
    """Detect stars FWHM in a frame.

    .. warning:: star positions must be known precisely

    :param frame: Frame

    :param star_list: List of the positions of the stars used to
      detect FWHM.

    :param fwhm_guess_pix: Initial guess on the FWHM of the stars.

    :return: (FWHM, FWHM_ERR) in pixels
    """
    FIT_BOXSZ_COEFF = 8

    # note that the fwhm guess is divided by two because it is better
    # to have a starting guess smaller than the real fwhm value
    fit_params = orb.cutils.multi_fit_stars(
        np.array(frame, dtype=float),
        np.array(star_list, dtype=float),
        int(np.nanmedian(fwhm_guess_pix*FIT_BOXSZ_COEFF)),
        height_guess=np.nanmedian(frame),
        fwhm_guess=np.atleast_1d(fwhm_guess_pix) / 2.,
        cov_height=False,
        cov_pos=True,
        cov_fwhm=True,
        fix_height=False,
        fix_pos=True,
        fix_fwhm=False,
        enable_zoom=False,
        enable_rotation=False,
        estimate_local_noise=False)


    if fit_params != []:
        return fit_params['stars-params'][:,4], fit_params['stars-params-err'][:,4]
    else:
        warnings.warn('FWHM could not be measured, check star positions')
        return None, None

def sources2list(sources):
    """Convert a sources pandas.DataFrame instance to a list of centroid
    """
    if 'xcentroid' not in sources or 'ycentroid' not in sources:
        raise TypeError('Badly formatted stars params')
        
    return np.array([sources['xcentroid'].values, sources['ycentroid'].values]).T

def multi_aperture_photometry(frame, pos_list, fwhm_guess_pix,
                              aper_coeff=3., detect_fwhm=False,
                              silent=False):
    """Aperture photometry of multiple sources in a frame.

    :param frame: Frame

    :param pos_list: List of the positions of the sources

    :param fwhm_guess_pix: Initial guess on the FWHM of the sources.

    :param aper_coeff: (Optional) Aperture coefficient used for
      photometry (default 3.).

    :param detect_fwhm: (Optional) If True FWHM is automatically
      computed from a fit on the sources. Sources must be stars or
      bright point sources. If most of the sources are stars this
      might work well enough (default False).

    :param silent: (Optional) Silent function if True (default False).
    """
    PHOT_BOXSZ_COEFF = 17
    pos_list = np.array(pos_list)
    if detect_fwhm:
        res = detect_fwhm_in_frame(
            frame, pos_list, fwhm_guess_pix)
        if res[0] is not None:
            fwhm_guess_pix, fwhm_err = res
        else:
            fwhm_err = np.nan
        if not silent:
            logging.info('Detected FWHM: {} [+/- {}] pixels'.format(
                np.nanmedian(fwhm_guess_pix), np.nanmedian(fwhm_err)))
    else:
        fwhm_err = np.empty(pos_list.shape[0], dtype=float)
        fwhm_err.fill(np.nan)

    if np.size(fwhm_guess_pix) <= 1:
        temp_arr = np.empty(pos_list.shape[0], dtype=float)
        temp_arr.fill(fwhm_guess_pix)
        fwhm_guess_pix = temp_arr

    results = list()
    pos_list = np.array(pos_list)
    aper_surf = None
    annu_surf = None
    for istar in range(pos_list.shape[0]):
        ix, iy = pos_list[istar, :2]
        x_min, x_max, y_min, y_max = orb.utils.image.get_box_coords(
            ix, iy, int(np.nanmedian(fwhm_guess_pix)*PHOT_BOXSZ_COEFF),
            0, frame.shape[0],
            0, frame.shape[1])
        star_box = frame[x_min:x_max, y_min:y_max]
        photom_result, aper_surf, annu_surf = aperture_photometry(
            star_box, fwhm_guess_pix[istar], aper_coeff=aper_coeff,
            return_surfaces=True, aperture_surface=aper_surf,
            annulus_surface=annu_surf)
        
        results.append({'aperture_flux':photom_result[0],
                        'aperture_flux_err':photom_result[1],
                        'aperture_surface':photom_result[2],
                        'aperture_flux_bad':photom_result[3],
                        'aperture_background':photom_result[4],
                        'aperture_background_err':photom_result[5],
                        'fwhm_pix':fwhm_guess_pix[istar],
                        'fwhm_pix_err':fwhm_err[istar]})
    return results

def load_star_list(star_list):
    """Load a list of stars coordinates from an hdffile or a pandas DataFrame or a numpy.ndarray

    :star_list: can be a np.ndarray of shape (n, 2) or a path to a star list
    """
    if isinstance(star_list, str):
        sources = pandas.read_hdf(star_list, key='data')
        star_list = sources2list(sources)

    elif isinstance(star_list, pandas.DataFrame):
        star_list = sources2list(star_list)

    else:
        if not isinstance(np.ndarray):
            raise TypeError('star_list must be an instance of numpy.ndarray or a path to a star list')
    if star_list.ndim != 2: raise TypeError('star list must have 2 dimensions')
    if star_list.shape[1] != 2: raise TypeError('badly formatted star list. must have shape (n, 2)')
    return star_list

def radial_profile(a, xc, yc, rmax):
    """Return the average radial profile on a region of a 2D array.

    :param a: A 2D array
    
    :param xc: Center of the profile along x axis
    
    :param yc: Center of the profile along y axis
    
    :param rmax: Radius of the profile

    :return: (R axis, V axis). A tuple of 2 vectors giving the radius
      axis and the corresponding values axis.
    """
    
    xmin = int(math.floor(xc-rmax))
    if xmin < 0: xmin = 0
    xmax = int(round(xc+rmax+1))
    if xmax > a.shape[0]: xmax = a.shape[0]
    ymin = int(math.floor(yc-rmax))
    if ymin < 0: ymin = 0
    ymax = int(round(yc+rmax+1))
    if ymax > a.shape[0]: ymax = a.shape[1]

    # collecting pixels values and their respective radius
    r_list = dict()
    for ii in range(xmin, xmax):
        for ij in range(ymin, ymax):
            r = np.sqrt(float(ii-xc)**2 + float(ij-yc)**2)
            v = a[ii,ij]
            if r in r_list:
                r_list[r] += list([v])
            else:
                r_list[r] = list([v])
            
    # reducing the list by averaging the values for each different radius
    reduced_r_list = list()
    for ir in r_list:
        reduced_r_list.append((ir, np.mean(r_list[ir]), len(r_list[ir])))

    reduced_r_list = np.array(reduced_r_list,
                              dtype=[('r', float), ('v', float), ('n', float)])
    reduced_r_list = np.sort(reduced_r_list, order='r')
    r_axis = np.array([reduced_r_list[ik][0]
                       for ik in range(reduced_r_list.shape[0])])
    v_axis = np.array([reduced_r_list[ik][1]
                       for ik in range(reduced_r_list.shape[0])])

    return (r_axis, v_axis)


def sky_background_level(im, smooth_coeff=0.1, return_mode=False, bins=25,
                         return_error=False):
    """Return the level of the sky background based on the maximum of
    the histogram of the pixels distribution in the image.

    :param im: Image.

    :param smooth_coeff: (Optional) the smoothing degree, i.e. the
      number of smoothing points is defined by smooth_coeff *
      size(histogram) (default 0.05). If smooth_coeff <= 0. no
      smoothing is applied.

    :param return_mode: (Optional) If True the returned value is the
      mode (an entire value for a distribution of integers). If False,
      return the mean of a sigmacut realized around the mode (a
      fractional value, generally more precise).

    :param bins: (Optional) Number of bins for the histogram (default
      20).

    :param return_error: (Optional) If True, the error on the
      estimation is returned (default False).
    """
    sig_im = orb.utils.stats.sigmacut(im, sigma=2.5)
    hist, bin_edges = np.histogram(sig_im, bins=bins)
    
    if np.size(hist) == 0.:
        warnings.warn(
            'Bad sky histogram: returning median of the distribution')
        return np.median(im)
    if smooth_coeff > 0.:
        hist = orb.utils.vector.smooth(
            hist, deg=int(smooth_coeff * bins) + 1,
            kind='gaussian_conv')
    index_max = np.argmax(hist)
    mode = (bin_edges[index_max] + bin_edges[index_max+1]) / 2.
    im_cut = orb.utils.stats.sigmacut(im, sigma=2.5, central_value=mode)
    if not return_error:
        return orb.utils.stats.robust_mean(im_cut)
    else:
        return orb.utils.stats.robust_mean(im_cut), (orb.utils.stats.robust_std(im_cut)
                                                 / math.sqrt(np.size(im_cut)))

def compute_radec_pm(ra_deg, dec_deg, pm_ra_mas, pm_dec_mas, yr):
    """Compute RA/DEC in degrees with proper motion values.

    :param ra_deg: RA in degrees

    :param dec_deg: DEC in degrees

    :param pm_ra_mas: Proper motion along RA axis in mas/yr

    :param pm_dec_mas: Proper motion along DEC axis in mas/yr

    :param yr: Number of years
    """
    ra = ra_deg + (pm_ra_mas * yr) * 1e-3 / 3600.
    dec = dec_deg + (pm_dec_mas * yr) * 1e-3 / 3600.
    if ra > 360. : ra -= 360.
    if ra < 0. : ra += 360.
    if dec > 90.: dec = 90. - dec
    if dec < 0.: dec = -dec
    return ra, dec

def ra2deg(ra):
    """Convert RA in sexagesimal format to degrees.

    :param ra: RA in sexagesimal format
    """
    ra = np.array(ra, dtype=float)
    if (ra.shape == (3,)):
        return (ra[0] + ra[1]/60. + ra[2]/3600.)*(360./24.)
    else:
        return None

def dec2deg(dec):
    """Convert DEC in sexagesimal format to degrees.

    :param dec: DEC in sexagesimal format
    """
    dec = np.array(dec, dtype=float)
    if (dec.shape == (3,)):
        if dec[0] >= 0:
            return dec[0] + dec[1]/60. + dec[2]/3600.
        else:
            return dec[0] - dec[1]/60. - dec[2]/3600.
    else:
        return None   

def deg2ra(deg, string=False):
    """Convert RA in degrees to sexagesimal.

    :param deg: RA in degrees
    """
    
    deg=float(deg)
    ra = np.empty((3), dtype=float)
    deg = deg*24./360.
    ra[0] = int(deg)
    deg = deg - ra[0]
    deg *= 60.
    ra[1] = int(deg)
    deg = deg - ra[1]
    deg *= 60.
    ra[2] = deg
    if not string:
        return ra
    else:
        return "%d:%d:%.2f" % (ra[0], ra[1], ra[2])

def deg2dec(deg, string=False):
    """Convert DEC in degrees to sexagesimal.

    :param deg: DEC in degrees
    """
    deg=float(deg)
    dec = np.empty((3), dtype=float)
    dec[0] = int(deg)
    deg = deg - dec[0]
    deg *= 60.
    dec[1] = int(deg)
    deg = deg - dec[1]
    deg *= 60.
    dec[2] = deg
    if (float("%.2f" % (dec[2])) == 60.0):
        dec[2] = 0.
        dec[1] += 1
    if dec[1] == 60:
        dec[0] += 1
    if dec[0] < 0:
        dec[1] = -dec[1]
        dec[2] = -dec[2]
    if not string:
        return dec
    else:
        return "+%d:%d:%.2f" % (dec[0], dec[1], dec[2])

def transform_star_position_A_to_B(star_list_A, params, rc, zoom_factor,
                                   sip_A=None, sip_B=None):
    """Transform star positions in camera A to the positions in camera
    B given the transformation parameters.

    Optionally SIP distorsion parameters can be given.

    The transformation steps are::
    
      dist_pix_camA -> perf_pix_camA -> geometric transformation_A2B
      -> perf_pix_camB -> dist_pix_camB

    :param star_list_A: List of star coordinates in the cube A.
    
    :param params: Transformation parameters [dx, dy, dr, da, db].
    
    :param rc: Rotation center coordinates.
    
    :param zoom_factor: Zooming factor between the two cameras. Can be
      a couple (zx, zy).
    
    :param sip_A: (Optional) pywcs.WCS instance containing SIP
      parameters of the frame A (default None).
      
    :param sip_B: (Optional) pywcs.WCS instance containing SIP
      parameters of the frame B (default None).
    """
    if np.size(zoom_factor) == 2:
        zx = zoom_factor[0]
        zy = zoom_factor[1]
    else:
        zx = float(zoom_factor)
        zy = float(zoom_factor)
        
    if not isinstance(star_list_A, np.ndarray):
        star_list_A = np.array(star_list_A)
    if star_list_A.dtype != np.dtype(float):
        star_list_A.astype(float)

    star_list_B = np.empty((star_list_A.shape[0], 2), dtype=float)

    # dist_pix_camA -> perf_pix_camA
    if sip_A is not None:
        #star_list_A = sip_pix2im(star_list_A, sip_A)
        ## star_list_A = sip_A.sip.pix2foc(star_list_A) + sip_A.wcs.crpix
        raise Exception('must be checked')
        
        
    # geometric transformation_A2B
    if np.any(params):
        for istar in range(star_list_A.shape[0]):
            star_list_B[istar,:] = orb.cutils.transform_A_to_B(
                star_list_A[istar,0], star_list_A[istar,1],
                params[0], params[1], params[2], params[3], params[4],
                rc[0], rc[1], zx, zy)
    else:
        star_list_B = np.copy(star_list_A)
        
    # perf_pix_camB -> dist_pix_camB
    if sip_B is not None:
        ## star_list_B = sip_im2pix(star_list_B, sip_B)
        raise Exception('must be checked')
        
    return star_list_B


def get_profile(profile_name):
    """Return the PSF profile class corresponding to the given profile name.

    :param profile name: The name of the PSF profile. Must be 'moffat'
      or 'gaussian'.
    
    """
    if profile_name == 'gaussian':
        return Gaussian
    elif profile_name == 'moffat':
        return Moffat
    else:
        raise ValueError("Bad profile name (%s) ! Profile name must be 'gaussian' or 'moffat'"%str(profile_name))
    
def fit_stars_in_frame(frame, star_list, box_size,
                       profile_name='gaussian', scale=None,
                       fwhm_pix=None, beta=3.5, fit_tol=1e-2,
                       fwhm_min=0.5, fix_height=None,
                       fix_aperture_fwhm_pix=None, fix_beta=True,
                       fix_fwhm=False,
                       readout_noise=10.,
                       dark_current_level=0.,
                       local_background=True,
                       no_aperture_photometry=False,
                       precise_guess=False, aper_coeff=3., blur=False,
                       no_fit=False, estimate_local_noise=True,
                       multi_fit=False, enable_zoom=False,
                       enable_rotation=False, saturation=None,
                       fix_pos=False, nozero=False, silent=True,
                       sip=None, background_value=None):

    ## WARNING : DO NOT CHANGE THE ORDER OF THE ARGUMENTS OR TAKE CARE
    ## OF THE CALL IN astrometry.Astrometry.fit_stars_in_cube()
  
    """Fit stars in a frame.

    .. note:: 2 fitting modes are possible:
    
      * Individual fit mode [multi_fit=False]: Stars are all fit
        independantly.
      
      * Multi fit mode [multi_fit=True]: Stars are fitted all together
        considering that the position pattern is well known, the same
        shift in x and y will be applied. Optionally the pattern can be
        rotated and zoomed. The FWHM is also considered to be the
        same. This option is far more robust and precise for alignment
        purpose.

    :param frame: The frame containing the stars to fit.

    :param star_list: A list of star positions as an array of shape
      (star_nb, 2)

    :param box_size: The size of the box created around a star to fit
      its parameter.

    :param profile_name: (Optional) Name of the PSF profile to use to
      fit stars. May be 'gaussian' or 'moffat' (default 'gaussian').

    :param fwhm_pix: (Optional) Estimate of the FWHM in pixels. If
      None given FWHM is estimated to half the box size (default
      None).

    :param scale: (Optional) Scale of the frame in arcsec/pixel. If
      given the fwhm in arcseconds is also computed (keyword:
      'fwhm_arc') with the fit parameters (default None).

    :param beta: (Optional) Beta parameter of the moffat psf. Used
      only if the fitted profile is a Moffat psf (default 3.5).

    :param fix_height: (Optional) Fix height parameter to its
      estimation. If None, set by default to True in individual fit
      mode [multi_fit=False] and False in multi fit mode
      [multi_fit=True] (default None).

    :param fix_beta: (Optional) Fix beta to the given value (default
      True).

    :param fix_fwhm: (Optional) Fix FWHM to the given value or the
      estimated value (default False).

    :param fix_pos: (Optional) Fix x,y positions of the stars to the
      given value.

    :param fit_tol: (Optional) Tolerance on the paramaters fit (the
      lower the better but the longer too) (default 1e-2).

    :param nozero: (Optional) If True do not fit any star which box
      (the pixels around it) contains a zero. Valid only in individual
      fit mode [multi_fit=False] (default False).

    :param fwhm_min: (Optional) Minimum valid FWHM of the fitted star
      (default 0.5)
      
    :param silent: (Optional) If True no messages are printed (default
      True).

    :param local_background: (Optional) If True, height is estimated
      localy, i.e. around the star. If False, the sky background is
      determined in the whole frame. In individual fit mode
      [multi_fit=False] height will be the same for all the stars, and
      the fix_height option is thus automatically set to True. In
      multi fit mode [multi_fit=True] height is considered as a
      covarying parameter for all the stars but it won't be fixed
      (default True).

    :param fix_aperture_fwhm_pix: (Optional) If a positive float. FWHM
      used to scale aperture size is not computed from the mean FWHM
      in the frame but fixed to the given float (default None).

    :param no_aperture_photometry: (Optional) If True, aperture
      photometry will not be done after profile fitting (default
      False).

    :param precise_guess: (Optional) If True, the fit guess will be
      more precise but this can lead to errors if the stars positions
      are not already well known. Valid only in individual fit mode
      [multi_fit=False] (default False).
          
    :param readout_noise: (Optional) Readout noise in ADU/pixel (can
      be computed from bias frames: std(master_bias_frame)) (default
      10.)
    
    :param dark_current_level: (Optional) Dark current level in
      ADU/pixel (can be computed from dark frames:
      median(master_dark_frame)) (default 0.)

    :param aper_coeff: (Optional) Aperture coefficient. The aperture
      radius is Rap = aper_coeff * FWHM. Better when between 1.5 to
      reduce the variation of the collected photons with varying FWHM
      and 3. to account for the flux in the wings (default 3., better
      for star with a high SNR).

    :param blur: (Optional) If True, blur frame (low pass filtering)
      before fitting stars. It can be used to enhance the quality of
      the fitted flux of undersampled data. Note that the error on
      star position can be greater on blurred frame. This option must
      not be used for alignment purpose (default False).

    :param no_fit: (Optional) If True, no fit is done. Only the
      aperture photometry. Star positions in the star list must thus
      be precise (default False).

    :param multi_fit: (Optional) If True all stars are fitted at the
      same time. More robust for alignment purpose. The difference of
      position between the stars in the star list must be precisely
      known because the overall shift only is estimated (default
      False).

    :param enable_zoom: (Optional) If True, the stars position pattern
      can be zoomed to better adjust it to the real frame. Valid only
      in multi fit mode [multi_fit=True] (default False).

    :param enable_rotation: (Optional) If True, the stars position
      pattern can be rotated to better adjust it to the real frame
      Valid only in multi fit mode [multi_fit=True] (default False).

    :param estimate_local_noise: (Optional) If True, the level of
      noise is computed from the background pixels around the
      stars. readout_noise and dark_current_level are thus not used
      (default True).

    :param saturation: (Optional) If not None, all pixels above the
      saturation level are removed from the fit (default None).

    :param sip: (Optional) A pywcs.WCS instance containing SIP
      distorsion correction (default None).

    :param background_value: (Optional) If not None, this background
      value is used in the fit functions and will be fixed for fit and
      aperture photometry. Note also that in this case
      local_background is automatically set to False (default None).
    
    :return: Parameters of a 2D fit of the stars positions.

    .. seealso:: :py:meth:`astrometry.Astrometry.load_star_list` to load
      a predefined list of stars or
      :py:meth:`astrometry.Astrometry.detect_stars` to automatically
      create it.

    .. seealso:: :meth:`utils.astrometry.fit_star` and
      :meth:`orb.cutils.multi_fit_stars`

    """
    BOX_COEFF = 7. # Coefficient to redefine the box size if the
                   # fitted FWHM is too large
    
    BIG_BOX_COEFF = 4. # Coefficient to apply to create a bigger box
                       # than the normal star box. This box is used for
                       # background determination and aperture
                       # photometry
                       
    BLUR_FWHM = 3.5   # FWHM of the gaussian kernel used to blur frames
    BLUR_DEG = int(math.ceil(
        BLUR_FWHM * 2. / (2. * math.sqrt(2. * math.log(2.)))))
    
    dimx = frame.shape[0]
    dimy = frame.shape[1]

    fitted_stars_params = list()
    fit_count = 0

    fit_results = list()

    star_list = np.array(star_list, dtype=float)

    if fix_height is None:
        if multi_fit: fix_height = False
        else: fix_height = True

    frame_median = bn.nanmedian(frame)
    
    if frame_median < 0.:
        frame -= frame_median
        warnings.warn('frame median is < 0 ({}), a value of {} has been subtracted to have a median at 0.'.format(frame_median, frame_median))
    
    ## Frame background determination if wanted
    background = None
    cov_height = False

    if background_value is not None:
        local_background = False
        background = background_value

    if not local_background and background_value is None:
        if precise_guess:
            background = utils.astrometry.sky_background_level(frame)
        else:
            background = frame_median
        if not multi_fit:
            fix_height = True
        else:
            cov_height = True
    
    ## Blur frame to avoid undersampled data
    if blur:
        fit_frame = np.copy(utils.image.low_pass_image_filter(
            frame, deg=BLUR_DEG))
        fwhm_pix = BLUR_FWHM
    else:
        fit_frame = np.copy(frame)

    ## Profile fitting
    if not no_fit:
        if multi_fit:
            if saturation is None: saturation = 0
            
            fit_params = orb.cutils.multi_fit_stars(
                np.array(fit_frame, dtype=float), np.array(star_list), box_size,
                height_guess=np.array(background, dtype=np.float),
                fwhm_guess=np.atleast_1d(fwhm_pix),
                cov_height=cov_height,
                cov_pos=True,
                cov_fwhm=True,
                fix_height=fix_height,
                fix_pos=fix_pos,
                fix_fwhm=fix_fwhm,
                fit_tol=fit_tol,
                ron=np.array(readout_noise, dtype=np.float),
                dcl=np.array(dark_current_level, dtype=np.float),
                enable_zoom=enable_zoom,
                enable_rotation=enable_rotation,
                estimate_local_noise=estimate_local_noise,
                saturation=saturation, sip=sip)
                
            # save results as a StarsParams instance
            for istar in range(star_list.shape[0]):
                if fit_params != []:
                    star_params = dict()
                    p = fit_params['stars-params'][istar, :]
                    e = fit_params['stars-params-err'][istar, :]
                    
                    star_params['height'] = p[0]
                    star_params['height_err'] = e[0]
                    star_params['amplitude'] = p[1]
                    star_params['amplitude_err'] = e[1]
                    star_params['snr'] = (star_params['amplitude']
                                          / star_params['amplitude_err'])
                    star_params['x'] = p[2]
                    star_params['x_err'] = e[2]
                    star_params['y'] = p[3]
                    star_params['y_err'] = e[3]
                    star_params['fwhm'] = p[4]
                    star_params['fwhm_pix'] = star_params['fwhm']
                    star_params['fwhm_err'] = e[4]
                    star_params['chi-square'] = fit_params['chi-square']
                    star_params['reduced-chi-square'] = fit_params[
                        'reduced-chi-square']
                    
                    star_params['flux'] = (
                        get_profile(profile_name))(
                        star_params).flux()
                    star_params['flux_err'] = (
                        get_profile(profile_name))(
                        star_params).flux_error(
                        star_params['amplitude_err'],
                        star_params['fwhm_err']
                        / abs(2.*math.sqrt(2. * math.log(2.))))
                    star_params['dx'] = star_params['x'] - star_list[istar,0]
                    star_params['dy'] = star_params['y'] - star_list[istar,1]
                    star_params['cov_angle'] = fit_params['cov_angle']
                    star_params['cov_zx'] = fit_params['cov_zx']
                    star_params['cov_zy'] = fit_params['cov_zy']
                    star_params['cov_dx'] = fit_params['cov_dx']
                    star_params['cov_dy'] = fit_params['cov_dy']
                    
                    if scale is not None:
                        star_params['fwhm_arc'] = (
                            float(star_params['fwhm_pix']) * scale)
                        star_params['fwhm_arc_err'] = (
                            float(star_params['fwhm_err']) * scale)
                    
                    fit_results.append(dict(star_params))
                else:
                    fit_results.append(None)
        else:
            for istar in range(star_list.shape[0]):        
                ## Create fit box
                guess = star_list[istar,:]
                if guess.shape[0] == 2:
                    [x_test, y_test] = guess
                elif guess.shape[0] >= 4:
                    [x_test, y_test] = guess[0:2]
                else:
                    raise ValueError("The star list must give 2 OR at least 4 parameters for each star [x, y, fwhm_x, fwhm_y]")

                if (x_test > 0 and x_test < dimx
                    and y_test > 0  and y_test < dimy):
                    (x_min, x_max,
                     y_min, y_max) = orb.utils.image.get_box_coords(
                        x_test, y_test, box_size,
                        0, dimx, 0, dimy)

                    star_box = fit_frame[x_min:x_max, y_min:y_max]
                else:
                    (x_min, x_max, y_min, y_max) = (
                        np.nan, np.nan, np.nan, np.nan)
                    star_box = np.empty((1,1))

                ## Profile Fitting
                if (min(star_box.shape) > float(box_size/2.)
                    and (x_max < dimx) and (x_min >= 0)
                    and (y_max < dimy) and (y_min >= 0)):

                    ## Local background determination for fitting
                    if local_background:
                        background_box_size = BIG_BOX_COEFF * box_size
                        (x_min_back,
                         x_max_back,
                         y_min_back,
                         y_max_back) = orb.utils.image.get_box_coords(
                            x_test, y_test, background_box_size,
                            0, dimx, 0, dimy)
                        background_box = fit_frame[x_min_back:x_max_back,
                                                   y_min_back:y_max_back]
                        if precise_guess:
                            background = sky_background_level(background_box)
                        else:
                            background = np.median(background_box)


                    if nozero and len(np.nonzero(star_box == 0)[0]) > 0:
                        fit_params = []

                    else:
                        fit_params = fit_star(
                            star_box, profile_name=profile_name,
                            fwhm_pix=fwhm_pix,
                            beta=beta, fix_height=fix_height,
                            fix_beta=fix_beta,
                            fix_fwhm=fix_fwhm,
                            fit_tol=fit_tol,
                            fwhm_min=fwhm_min,
                            height=background,
                            ron=readout_noise,
                            dcl=dark_current_level,
                            precise_guess=precise_guess,
                            estimate_local_noise=estimate_local_noise,
                            saturation=saturation)
                else:
                    fit_params = []

                if (fit_params != []):
                    fit_count += 1
                    # compute real position in the frame
                    fit_params['x'] += float(x_min)
                    fit_params['y'] += float(y_min)

                    # compute deviation from the position given in the
                    # star list (the center of the star box)
                    fit_params['dx'] = fit_params['x'] - x_test
                    fit_params['dy'] = fit_params['y'] - y_test

                    # compute FWHM in arcsec
                    if scale is not None:
                        fit_params['fwhm_arc'] = (float(fit_params['fwhm_pix'])
                                                  * scale)
                        fit_params['fwhm_arc_err'] = (
                            float(fit_params['fwhm_err']) * scale)

                    # save results
                    fit_results.append(dict(fit_params))
                else:
                    fit_results.append(None)

    else: # if no_fit fit_results is filled with None
        for istar in range(star_list.shape[0]):
            fit_results.append(None)
        
    ## Compute aperture photometry
    if not no_aperture_photometry:
        
        if not no_fit:
            # get mean FWHM in the frame
            if fix_aperture_fwhm_pix is not None:
                if fix_aperture_fwhm_pix > 0.:
                    mean_fwhm = fix_aperture_fwhm_pix
                else:
                    raise ValueError(
                        'Fixed FWHM for aperture photometry must be > 0.')
            elif star_list.shape[0] > 1:
                mean_fwhm = orb.utils.stats.robust_mean(
                    orb.utils.stats.sigmacut(
                    [ires['fwhm_pix'] for ires in fit_results if ires is not None]))
            else:
                mean_fwhm = fit_results[0]['fwhm_pix']
        else:
            mean_fwhm = fwhm_pix

        ## Local background determination for aperture
        if local_background:
            background = None
        
        # get aperture given the mean FWHM
        for istar in range(star_list.shape[0]):
            if (fit_results[istar] is not None) or (no_fit):
                new_box_size = BOX_COEFF * mean_fwhm
                aperture_box_size = BIG_BOX_COEFF * max(box_size, new_box_size)
               
                if not no_fit:
                    ix = fit_results[istar]['x']
                    iy = fit_results[istar]['y']
                else:
                    ix = star_list[istar,0]
                    iy = star_list[istar,1]
                if ix > 0 and ix < dimx and iy > 0  and iy < dimy:
                    (x_min, x_max,
                     y_min, y_max) = orb.utils.image.get_box_coords(
                        ix, iy, aperture_box_size, 0, dimx, 0, dimy)
                    star_box = frame[x_min:x_max, y_min:y_max]
                    
                    photom_result = aperture_photometry(
                        star_box, mean_fwhm, background_guess=background,
                        aper_coeff=aper_coeff)
                    
                    if no_fit:
                        fit_params = {'aperture_flux':photom_result[0],
                                      'aperture_flux_err':photom_result[1],
                                      'aperture_surface':photom_result[2],
                                      'aperture_flux_bad':photom_result[3],
                                      'aperture_background':photom_result[4],
                                      'aperture_background_err':photom_result[5]}
                        
                        fit_results[istar] = fit_params

                    else:
                        fit_results[istar]['aperture_flux'] = (
                            photom_result[0])
                        fit_results[istar]['aperture_flux_err'] = (
                            photom_result[1])
                        fit_results[istar]['aperture_surface'] = (
                            photom_result[2])
                        fit_results[istar]['aperture_flux_bad'] = (
                            photom_result[3])
                        fit_results[istar]['aperture_background'] = (
                            photom_result[4])
                        fit_results[istar]['aperture_background_err'] = (
                            photom_result[5])
                        
                    
        
    ## Print number of fitted stars
    if not silent:
        logging.info("%d/%d stars fitted" %(len(fitted_stars_params), star_list.shape[0]))

    return fit_results



def fit_sip(dimx, dimy, scale, star_list1, star_list2, params=None, init_sip=None,
            err=None, sip_order=4, crpix=None, crval=None):
    """FIT the distortion correction polynomial to match two lists
    of stars (the list of stars 2 is distorded to match the list
    of stars 1).

    :param dimx: X dimension of the image

    :param dimy: Y dimension of the image

    :param scale: Plate scale of the image in arcseconds

    :param star_list1: list of stars 1

    :param star_list2: list of stars 2

    :param params: (Optional) Transformation parameter to go from
      the list of stars 1 to the list of stars 2. Must be a tuple
      [dx, dy, dr, da, db, rcx, rcy, zoom_factor] (default None).

    :param init_sip: (Optional) Initial SIP (an astropy.wcs.WCS object,
      default None)

    :param err: (Optional) error on the star positions of the star
      list 2 (default None).

    :param sip_order: (Optional) SIP order (default 3).

    :param crpix: (Optional) If an initial wcs is not given (init_sip
      set to None) this header value must be given.

    :param crval: (Optional) If an initial wcs is not given (init_sip
      set to None) this header value must be given.
    """
    def p2sip(p, sip, direct):
        if direct:
            sip.sip.a[:] = np.reshape(
                p[:(sip.sip.a_order + 1)**2],
                (sip.sip.a_order + 1, sip.sip.a_order + 1))
            p = p[(sip.sip.a_order + 1)**2:]
            sip.sip.b[:] = np.reshape(
                p[:(sip.sip.b_order + 1)**2],
                (sip.sip.b_order + 1, sip.sip.b_order + 1))
        else:
            sip.sip.ap[:] = np.reshape(
                p[:(sip.sip.a_order + 1)**2],
                (sip.sip.a_order + 1, sip.sip.a_order + 1))
            p = p[(sip.sip.a_order + 1)**2:]
            sip.sip.bp[:] = np.reshape(
                p[:(sip.sip.b_order + 1)**2],
                (sip.sip.b_order + 1, sip.sip.b_order + 1))
        return sip

    def sip2p(sip, direct):
        p = list()
        if direct:
            p += list(sip.sip.a.flatten())
            p += list(sip.sip.b.flatten())
        else:
            p += list(sip.sip.ap.flatten())
            p += list(sip.sip.bp.flatten())
        return p

    def diff(p, star_list2, star_list_deg1, 
             params, sip, err, direct):
        sip = p2sip(p, sip, direct)
        try:
            if direct:
                star_list_1t = sip.all_world2pix(star_list_deg1, 0)
            
                ## star_list_1t = transform_star_position_A_to_B(
                ##     star_list1, params[:5],
                ##     (params[5], params[6]),
                ##     (params[7], params[8]),
                ##     sip_A=None, sip_B=None)

                dx = (star_list2 - star_list_1t)[:,0]
                dy = (star_list2 - star_list_1t)[:,1]

            else:
                star_list_2t = sip.all_pix2world(star_list2, 0)
                star_list_2t = sip.all_world2pix(star_list_2t, 0)
                            
                dx = (star_list_2t - star_list2)[:,0]
                dy = (star_list_2t - star_list2)[:,1]

            result = np.array(list(dx/err) + list(dy/err))
            if not np.all(np.isnan(result)):
                return math.sqrt(np.nanmean(result**2.))
            else: return 1e9
        except Exception, e:
            import warnings
            warnings.warn(str(e))
            return 1e9

    def add_sip(wcs):
        wcs.wcs.ctype = ["RA---TAN-SIP", "DEC--TAN-SIP"]
        wcs.sip = pywcs.wcs.Sip(np.zeros((sip_order + 1, sip_order + 1)),
                                np.zeros((sip_order + 1, sip_order + 1)),
                                np.zeros((sip_order + 1, sip_order + 1)),
                                np.zeros((sip_order + 1, sip_order + 1)),
                                wcs.wcs.crpix)
        return wcs



    if params is not None:
        raise Exception('Not implemented')


    # initialize WCS and SIP if not given
    if init_sip is None:
        if crpix is None or crval is None:
            raise Exception('If an initial wcs is not given (init_sip set to None) CRPIX and CRVAL must be given.')
        
        init_sip = create_wcs(crpix[0], crpix[1],
                              scale / 3600., scale / 3600.,
                              crval[0], crval[1], 0.)
    else: # WCS copy to avoid modifing the original WCS
        init_sipt = pywcs.WCS(init_sip.to_header(relax=True))
        init_sipt.sip = copy.copy(init_sip.sip)
        init_sip = init_sipt
        
    if init_sip.sip is None:
        init_sip = add_sip(init_sip)

    # computation of a reference ra/dec list of stars from the
    # reference list of pixels (star_list1)
    star_list_deg1 = init_sip.all_pix2world(star_list1, 0)

    if err is None:
        err = np.ones(star_list1.shape[0], dtype=float)
    elif np.all(np.isnan(err)):
        err = np.ones(star_list1.shape[0], dtype=float)

    err /= np.nanmean(err)

    guess = np.array(sip2p(init_sip, True))

    # look for direct transformation parameters (A, B matrices)
    fit = optimize.fmin(diff, guess,
                        args=(star_list2, star_list_deg1, params,
                              init_sip, err, True),
                        full_output=True, xtol=1e-6, disp=False)

    if fit[-1] <= 4:
        logging.info('Optimized average radius for direct transformation (in pixel) {}'.format(fit[1]))
        init_sip = p2sip(fit[0], init_sip, True)

    else:
        raise Exception('SIP direct transformation fit failed')

    # look for reverse transformation parameters (AP, BP matrices)
    fit = optimize.fmin(diff, -fit[0],
                        args=(star_list2, star_list_deg1, params,
                              init_sip, err, False),
                        full_output=True, xtol=1e-6, disp=False)

    if fit[-1] <= 4:
        logging.info('Optimized average radius for reverse transformation (in pixel) {}'.format(fit[1]))
        new_wcs = p2sip(fit[0], init_sip, False)
        new_wcs.wcs.cd = np.dot(np.diag(new_wcs.wcs.get_cdelt()),
                                new_wcs.wcs.get_pc())
            
        return new_wcs

    else:
        raise Exception('SIP reverse transformation fit failed')
    

def histogram_registration(star_list1, star_list2, dimx, dimy, xy_bins):
    """Fast histogram registration of an image based on the comparison
    of two star lists: one created from the real star position in the
    image and the other from, e.g. a catalog.

    :param star_list1: first list of stars

    :param star_list2: second list of stars

    :param dimx: X dimension of the image in pixels

    :param dimy: Y dimension of the image inp ixels

    :param xy_bins: number of bins along X and Y

    .. warning:: This kind of registration is very sensitive to the
      angle between each list. It is better to use it on a range of
      angles (steps of 0.5 degree) to make sure the best correlation
      is found.
    """

    hist_bins = np.linspace(0, max(dimx, dimy), xy_bins)
    hist1, axes = np.histogramdd(
        star_list1, bins=[hist_bins,hist_bins])
    hist2, axes = np.histogramdd(
        star_list2, bins=[hist_bins,hist_bins])
    hist_corr = signal.correlate2d(hist1, hist2, mode='same')
    max_index = np.unravel_index(np.nanargmax(hist_corr), hist1.shape)
    max_corr = np.nanmax(hist_corr)
    max_dx = hist_bins[max_index[0]] - dimx / 2.
    max_dy = hist_bins[max_index[1]] - dimx / 2.

    return max_corr, max_dx, max_dy    


def create_wcs(target_x, target_y, deltax, deltay, target_ra,
               target_dec, rotation, sip=None):
    """Create a WCS with an optional SIP distortion model.

    :param wcs: Original WCS. If None, a 2 axis WCS is created instead.

    :param target_x: Target X position in pixels

    :param target_y: Target Y position in pixels

    :param deltax: Plate scale in arcdeg / pixel along X axis (don't forget to
      divide by 3600 if originally in arcsec by pixels)

    :param deltax: Plate scale in arcdeg / pixel along Y axis (don't forget to
      divide by 3600 if originally in arcsec by pixels)

    :param target_ra: Target RA

    :param target_dec: Target DEC

    :param rotation: Rotation angle

    :param sip: (Optional) astropy.WCS instance containing a valid SIP.
    """

    _wcs = pywcs.WCS(naxis=2) # a new WCS must be created. Never update
                             # an old WCS!
        
    _wcs.wcs.crpix = [target_x, target_y]
    _wcs.wcs.cdelt = np.array([-deltax, deltay])
    _wcs.wcs.crval = [target_ra, target_dec]
    # !! must stay here because get_pc does not work with RA---TAN-SIP type
    _wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"] 
    _wcs.wcs.crota = [rotation, rotation]
    # force wcs to CD definition (for SIP)
    _wcs.wcs.cd = np.dot(
        np.diag(_wcs.wcs.get_cdelt()),
        _wcs.wcs.get_pc())
    _wcs.wcs.ctype = ["RA---TAN-SIP", "DEC--TAN-SIP"]
    _wcs.wcs.radesys = 'FK5'
    _wcs.wcs.equinox = 2000.
    del _wcs.wcs.crota
    if sip is not None:
        _wcs.sip = sip.sip
    return _wcs

def get_wcs_parameters(_wcs):
    """Return comprehensive parameters from a simple WCS as created
    with orb.utils.astrometry.create_wcs.

    :param wcs: An astropy.wcs.WCS instance created with
      orb.utils.astrometry.create_wcs.

    :return: target_x, target_y, deltax, deltay, target_ra,
      target_dec, rotation
    """
    target_x, target_y = _wcs.wcs.crpix
    target_ra, target_dec = _wcs.wcs.crval
    try:
        cd = np.copy(_wcs.wcs.cd)
        warnings.warn('CD_ij based WCS is not recommended. Please prefer a PC_ij representation.')
        rotation = np.rad2deg(np.arctan2(-cd[0,1], -cd[0,0]))
        deltax = - cd[0,0] / np.cos(np.deg2rad(rotation))
        deltay = - cd[0,1] / np.sin(np.deg2rad(rotation))
        
    except AttributeError: # no cd is present
        pc = np.copy(_wcs.wcs.get_pc())
        deltax, deltay = _wcs.wcs.cdelt
        rotation = np.rad2deg(np.arctan2(-pc[0,1]/deltax, -pc[0,0]/deltax))
        if np.isclose(np.abs(rotation), 180): rotation = 0.

        check_angle = np.rad2deg(np.arctan2(-pc[1,0]/deltay, pc[1,1]/deltay))
        if not np.isclose(check_angle, rotation):
            raise RuntimeError('Malformed PC_ij matrix ? ({} not close to {})'.format(check_angle, rotation))
        deltax = abs(deltax)
        deltay = abs(deltay)

    if deltax < 0.: raise StandardError('deltax and deltay must be equal and > 0')
    if abs(rotation) > 90. : raise StandardError('rotation angle is {} must be < 90. There must be an error.'.format(rotation))
    #if not np.allclose(deltax, deltay): raise StandardError('deltax ({}) must be equal to deltay ({})'.format(deltax, deltay))
    deltay = float(deltax)
    
    return target_x, target_y, deltax, deltay, target_ra, target_dec, rotation

def brute_force_guess(image, star_list, x_range, y_range, r_range,
                      rc, zoom_factor, box_size, verbose=True, init_wcs=None,
                      raise_border_error=True):
    """Determine a precise alignment guess by brute force.

    :param star_list: List of star position. Must be given in pixels
      if no wcs is given (wcs set to None). If a wcs is given must be a
      list of ra/dec coordinates.

    :param x_range: range of x values to check

    :param y_range: range of y values to check

    :param r_range: range of angle values to check

    :param rc: rotation center (rc, ry). If a WCS is given the
      rotation center is obtaind from the wcs itself and must be set to
      None.

    :param zoom_factor: zoom_factor

    :param verbose: (Optional) If True, print some informations
      (default True).

    :param init_wcs: (Optional) WCS instance (can contain an SIP distortion
      model, default None).

    :param raise_border_error: (Optional) if True raise an exception
      if the returned guess is on the border of the brute force grid
      (defaut True).
    """

    def get_total_flux(guess_list, image, star_list,
                       rc, zoom_factor, box_size, kernel, _wcs_str, _wcsp):
        """Return the sum of the flux around a transformed list of
        star positions for a list of parameters.        
        """
        if _wcs_str is None:
            _wcs = None
        else:
            _wcs = pywcs.WCS(_wcs_str)
        result = np.empty((guess_list.shape[0], 4))
        result.fill(np.nan)
        if _wcsp is not None and _wcs is not None:
            (target_x, target_y, deltax, deltay,
             target_ra, target_dec, rotation) = _wcsp
                
        for ik in range(guess_list.shape[0]):
            guess = (guess_list[ik, 0],
                     guess_list[ik, 1],
                     guess_list[ik, 2], 0., 0.)

            if _wcs is not None:
                iwcs = create_wcs(
                    target_x - guess[0],
                    target_y - guess[1],
                    deltax * zoom_factor,
                    deltay * zoom_factor,
                    target_ra, target_dec,
                    rotation - guess[2], sip=_wcs)
                star_list = np.array(star_list)
                star_list_t = np.array(iwcs.all_world2pix(
                    star_list[:,0],
                    star_list[:,1], 0, quiet=True)).T
                star_list2 = list()
                # removing stars not in the image
                for istar in range(star_list_t.shape[0]):
                    if (star_list_t[istar,0] > 0.
                        and star_list_t[istar,0] < image.shape[0]
                        and star_list_t[istar,1] > 0.
                        and star_list_t[istar,1] < image.shape[1]):
                        star_list2.append(star_list_t[istar,:])
                star_list2 = np.array(star_list2)
            else:
                star_list2 = transform_star_position_A_to_B(
                    np.copy(star_list), guess, rc, zoom_factor)

            total_flux = orb.cutils.brute_photometry(
                image, star_list2, kernel, box_size)
            result[ik, 0] = total_flux
            result[ik, 1:] = guess_list[ik]
        return result
    
    if init_wcs is not None and rc is not None:
        warnings.warn('rc must be set to None if a wcs is given. rc automatically set to None.')
        rc = None

    if init_wcs is None and rc is None:
        warnings.warn('rc automatically set.')
        rc = (image.shape[0]/2., image.shape[1]/2.)

    if verbose:
        logging.info('Brute force range:')
        if len(x_range) > 1:
            logging.info('X = {:.2f}:{:.2f}:{:.2f}'.format(
                np.min(x_range), np.max(x_range), x_range[1] - x_range[0]))
        if len(y_range) > 1:
            logging.info('Y = {:.2f}:{:.2f}:{:.2f}'.format(
                np.min(y_range), np.max(y_range), y_range[1] - y_range[0]))
        if len(r_range) > 1:
            logging.info('R = {:.2f}:{:.2f}:{:.2f}'.format(
                np.min(r_range), np.max(r_range), r_range[1] - r_range[0]))


    guess_list = list()
    guess_matrix = np.empty((len(x_range),
                             len(y_range),
                             len(r_range)), dtype=float)
    guess_matrix_index_list = list()

    box_size = int(box_size)
    if not box_size&1: box_size += 1 # box_size must be odd
    kernel = orb.cutils.gaussian_array2d(0., 1., box_size /2. - 0.5,
                                         box_size /2. - 0.5, box_size / 3.,
                                         box_size, box_size)
    kernel /= np.nansum(kernel)

    for idx in range(len(x_range)):
        for idy in range(len(y_range)):
            for idr in range(len(r_range)):
                guess_matrix_index_list.append((idx, idy, idr))
                guess_list.append(np.array([x_range[idx],
                                            y_range[idy],
                                            r_range[idr]]))

    guess_list = np.array(guess_list)
    # Init of the multiprocessing server
    job_server, ncpus = orb.utils.parallel.init_pp_server()
    ncpus_max = ncpus

    # divide guess list in smaller lists for parallelization
    pguess_cut_indexes = np.linspace(
        0, guess_list.shape[0], ncpus_max+1).astype(int)
    pguess_lists = [guess_list[
        pguess_cut_indexes[i]:pguess_cut_indexes[i+1]]
                    for i in range(ncpus_max)]

    total_flux_list = np.empty((guess_list.shape[0], 4), dtype=float)

    if init_wcs is not None:
        wcs_params = get_wcs_parameters(init_wcs)
        init_wcs_str = init_wcs.to_header_string(relax=True)
    else:
        wcs_params = None
        init_wcs_str = None

    # parallel processing of each guess list part
    jobs = [(ijob, job_server.submit(
        get_total_flux, 
        args=(pguess_lists[ijob], image,
              star_list, rc, zoom_factor,
              box_size, kernel, init_wcs_str, wcs_params),
        modules=("import logging",
                 "import numpy as np",
                 "import astropy.wcs as pywcs",
                 "import orb.cutils",
                 "import warnings",
                 "from orb.utils.astrometry import *",
                 "import astropy.io.fits as pyfits")))
            for ijob in range(ncpus)]

    for ijob, job in jobs:
        total_flux_list[
            pguess_cut_indexes[ijob]
            :pguess_cut_indexes[ijob + 1], :] = job()

    orb.utils.parallel.close_pp_server(job_server)

    # rebuilding guess matrix
    for ik in range(guess_list.shape[0]):
        guess_matrix[
            guess_matrix_index_list[ik][0],
            guess_matrix_index_list[ik][1],
            guess_matrix_index_list[ik][2]] = total_flux_list[ik, 0]

    # avoid a negative guess matrix
    guess_matrix -= np.nanmin(guess_matrix)

    # maximum value of the guess matrix is the best estimate
    rough_dx, rough_dy, rough_dr =  np.unravel_index(
        np.argmax(guess_matrix), guess_matrix.shape)

    index1d = np.ravel_multi_index((rough_dx, rough_dy, rough_dr),
                                   guess_matrix.shape)

    dx = total_flux_list[index1d, 1]
    dy = total_flux_list[index1d, 2]
    dr = total_flux_list[index1d, 3]

    if verbose:
        logging.info('Brute force guess:\ndx = {}\ndy = {} \ndr = {}'.format(
            dx, dy, dr))

    if raise_border_error:
        if (dx == np.min(x_range)
            or dx == np.max(x_range)
            or dy == np.min(y_range)
            or dy == np.max(y_range)
            or dr == np.min(r_range)
            or dr == np.max(r_range)):
            raise Exception('Brute force maximum found on grid border !')
        

    return dx, dy, dr, np.squeeze(guess_matrix)



def world2pix(hdr, dimx, dimy, star_list_deg, dxmap, dymap):
    """Convert RA/DEC coordinates to pixel positions.

    :param hdr: pyfits.Header instance

    :param dimx: Image dimension along X

    :param dimy: Image dimension along Y

    :param star_list_deg: List of star coordinates in degrees

    :param dxmap: Distortion error map along X axis returned by
      orb.astrometry.Astrometry.register().

    :param dymap: Distortion error map along Y axis returned by
      orb.astrometry.Astrometry.register().

    .. note:: it is much more effficient to pass a list of coordinates
      than run the function for each couple of coordinates you want to
      transform.
    """
    dxspl = interpolate.RectBivariateSpline(
        np.linspace(0, dimx, dxmap.shape[0]),
        np.linspace(0, dimy, dxmap.shape[1]),
        dxmap, kx=3, ky=3)
    
    dyspl = interpolate.RectBivariateSpline(
        np.linspace(0, dimx, dymap.shape[0]),
        np.linspace(0, dimy, dymap.shape[1]),
        dymap, kx=3, ky=3)

    wcs = pywcs.WCS(hdr, relax=True)
    
    star_list_pix = np.array(
        wcs.all_world2pix(
            star_list_deg[:,0],
            star_list_deg[:,1], 0,
            detect_divergence=False,
            quiet=True)).T

    dx = dxspl.ev(star_list_pix[:,0],
                  star_list_pix[:,1])
    dy = dyspl.ev(star_list_pix[:,0],
                  star_list_pix[:,1])

    star_list_pix[:,0] += dx
    star_list_pix[:,1] += dy

    return star_list_pix

    
def pix2world(hdr, dimx, dimy, star_list_pix, dxmap, dymap):
    """Convert pixel positions to RA/DEC coordinates.

    :param hdr: pyfits.Header instance

    :param dimx: Image dimension along X

    :param dimy: Image dimension along Y

    :param star_list_pix: List of star coordinates in pixels

    :param dxmap: Distortion error map along X axis returned by
      orb.astrometry.Astrometry.register().

    :param dymap: Distortion error map along Y axis returned by
      orb.astrometry.Astrometry.register().

    .. note:: it is much more effficient to pass a list of coordinates
      than run the function for each couple of coordinates you want to
      transform.
    """
    dxspl = interpolate.RectBivariateSpline(
        np.linspace(0, dimx, dxmap.shape[0]),
        np.linspace(0, dimy, dxmap.shape[1]),
        dxmap, kx=3, ky=3)
    
    dyspl = interpolate.RectBivariateSpline(
        np.linspace(0, dimx, dymap.shape[0]),
        np.linspace(0, dimy, dymap.shape[1]),
        dymap, kx=3, ky=3)

    wcs = pywcs.WCS(hdr, relax=True)
    dx = dxspl.ev(star_list_pix[:,0],
                  star_list_pix[:,1])
    dy = dyspl.ev(star_list_pix[:,0],
                  star_list_pix[:,1])

    star_list_pixt = np.copy(star_list_pix)
    star_list_pixt[:,0] -= dx
    star_list_pixt[:,1] -= dy

    star_list_deg = np.array(
        wcs.all_pix2world(
            star_list_pixt[:,0],
            star_list_pixt[:,1], 0)).T

    return star_list_deg


def realign_images(_cube):
    """Realign images of a small cube of images

    :param _cube: A 3 dimensional np.ndarray.

    .. warning:: This procedure is robust but very slow. Do not use it
      to realign a large number of images.
    """
    
    im1 = _cube[:,:,0]
    dimz = _cube.shape[2]
    src1_list = np.nonzero(im1 > np.nanpercentile(im1, 99.9))
    agg1_list = orb.utils.misc.aggregate_pixels(src1_list)

    isrcx = list() ; isrcy = list()
    for isrc in agg1_list:
        isrc = np.array(isrc)
        isrcx.append(np.nanmean(isrc[:,0]))
        isrcy.append(np.nanmean(isrc[:,1]))
    isrcx = np.array(isrcx)
    isrcy = np.array(isrcy)

    for ik in range(1, dimz):
        # detect sources
        im2 = _cube[:,:,ik]
        src2_list = np.nonzero(im2 > np.nanpercentile(im2, 99.9))
        agg2_list = orb.utils.misc.aggregate_pixels(src2_list)
        isrcx2 = list() ; isrcy2 = list()
        for isrc2 in agg2_list:
            isrc2 = np.array(isrc2)
            isrcx2.append(np.nanmean(isrc2[:,0]))
            isrcy2.append(np.nanmean(isrc2[:,1]))
        isrcx2 = np.array(isrcx2)
        isrcy2 = np.array(isrcy2)

        neix = list()
        neiy = list()
        for ii in range(isrcx.size):
            idx = isrcx2 - isrcx[ii]
            idy = isrcy2 - isrcy[ii]
            ir = np.sqrt(idx**2. + idy**2.)
            inei = np.nanargmin(ir)
            neix.append(idx[inei])
            neiy.append(idy[inei])

        dx = -np.nanmean(orb.utils.stats.sigmacut(neix, sigma=2.))
        dy = -np.nanmean(orb.utils.stats.sigmacut(neiy, sigma=2.))

        logging.info('dx: {}, dy: {}'.format(dx, dy))
        _cube[:,:,ik] = orb.utils.image.transform_frame(
            im2, 0, im2.shape[0], 0, im2.shape[1], [dx, dy, 0, 0, 0],
            (im2.shape[0]/2., im2.shape[1]/2.), 1., 1)
    return _cube

def fit2df(fit):
    """Convert fit results to a pandas.DataFrame instance
    """
    df = dict()
    keys = None
    for istar in fit:
        if keys is None:
            if istar is None: continue
            keys = istar.keys()
            for ikey in keys:
                df[ikey] = list()
        for ikey in keys:
            if istar is not None:
                df[ikey].append(istar[ikey])
            else:
                df[ikey].append(np.nan)

    df = pandas.DataFrame(df)
    return df
