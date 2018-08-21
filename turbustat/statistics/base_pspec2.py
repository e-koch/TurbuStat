# Licensed under an MIT open source license - see LICENSE
from __future__ import print_function, absolute_import, division

import numpy as np
import statsmodels.api as sm
import warnings
import astropy.units as u

from .lm_seg import Lm_Seg
from .psds import pspec, make_radial_freq_arrays
from .fitting_utils import clip_func
from .elliptical_powerlaw import (fit_elliptical_powerlaw,
                                  inverse_interval_transform,
                                  inverse_interval_transform_stderr)
from .apodizing_kernels import *


class StatisticBase_PSpec2D(object):
    """
    Common features shared by 2D power spectrum methods.
    """

    @property
    def ps2D(self):
        '''
        Two-dimensional power spectrum.
        '''
        return self._ps2D[::-1]

    @property
    def ps1D(self):
        '''
        One-dimensional power spectrum.
        '''
        return self._ps1D

    @property
    def ps1D_stddev(self):
        '''
        1-sigma standard deviation of the 1D power spectrum.
        '''
        if not self._stddev_flag:
            warnings.warn("ps1D_stddev is only calculated when return_stddev"
                          " is enabled.")

        return self._ps1D_stddev

    @property
    def freqs(self):
        '''
        Corresponding spatial frequencies of the 1D power spectrum.
        '''
        return self._freqs

    @property
    def wavenumbers(self):
        return self._freqs * min(self._ps2D.shape)

    def compute_radial_pspec(self, return_stddev=True,
                             logspacing=False, max_bin=None, **kwargs):
        '''
        Computes the radially averaged power spectrum.

        Parameters
        ----------
        return_stddev : bool, optional
            Return the standard deviation in the 1D bins.
        logspacing : bool, optional
            Return logarithmically spaced bins for the lags.
        max_bin : float, optional
            Maximum spatial frequency to bin values at.
        kwargs : passed to `~turbustat.statistics.psds.pspec`.
        '''

        # Check if azimuthal constraints are given
        if kwargs.get("theta_0"):
            azim_constraint_flag = True
        else:
            azim_constraint_flag = False

        out = pspec(self.ps2D, return_stddev=return_stddev,
                    logspacing=logspacing, max_bin=max_bin, **kwargs)

        self._stddev_flag = return_stddev
        self._azim_constraint_flag = azim_constraint_flag

        if return_stddev and azim_constraint_flag:
            self._freqs, self._ps1D, self._ps1D_stddev, self._azim_mask = out
        elif return_stddev:
            self._freqs, self._ps1D, self._ps1D_stddev = out
        elif azim_constraint_flag:
            self._freqs, self._ps1D, self._azim_mask = out
        else:
            self._freqs, self._ps1D = out

        # Attach units to freqs
        self._freqs = self.freqs / u.pix

    def fit_pspec(self, brk=None, log_break=False, low_cut=None,
                  high_cut=None, min_fits_pts=10, weighted_fit=False,
                  verbose=False):
        '''
        Fit the 1D Power spectrum using a segmented linear model. Note that
        the current implementation allows for only 1 break point in the
        model. If the break point is estimated via a spline, the breaks are
        tested, starting from the largest, until the model finds a good fit.

        Parameters
        ----------
        brk : float or None, optional
            Guesses for the break points. If given as a list, the length of
            the list sets the number of break points to be fit. If a choice is
            outside of the allowed range from the data, Lm_Seg will raise an
            error. If None, a spline is used to estimate the breaks.
        log_break : bool, optional
            Sets whether the provided break estimates are log-ed (base 10)
            values. This is disabled by default. When enabled, the brk must
            be a unitless `~astropy.units.Quantity`
            (`u.dimensionless_unscaled`).
        low_cut : `~astropy.units.Quantity`, optional
            Lowest frequency to consider in the fit.
        high_cut : `~astropy.units.Quantity`, optional
            Highest frequency to consider in the fit.
        min_fits_pts : int, optional
            Sets the minimum number of points needed to fit. If not met, the
            break found is rejected.
        weighted_fit : bool, optional
            Fit using weighted least-squares. Requires `return_stddev` to be
            enabled when computing the radial power-spectrum. The weights are
            the inverse-squared standard deviations in each radial bin.
        verbose : bool, optional
            Enables verbose mode in Lm_Seg.
        '''

        # Make the data to fit to
        if low_cut is None:
            # Default to the largest frequency, since this is just 1 pixel
            # in the 2D PSpec.
            self.low_cut = 1. / (0.5 * float(max(self.ps2D.shape)) * u.pix)
        else:
            self.low_cut = self._to_pixel_freq(low_cut)

        if high_cut is None:
            self.high_cut = self.freqs.max().value / u.pix
        else:
            self.high_cut = self._to_pixel_freq(high_cut)

        x = np.log10(self.freqs[clip_func(self.freqs.value, self.low_cut.value,
                                          self.high_cut.value)].value)
        y = np.log10(self.ps1D[clip_func(self.freqs.value, self.low_cut.value,
                                         self.high_cut.value)])

        if weighted_fit:

            if brk is not None:
                raise ValueError("Weighted least-squares fitting cannot be "
                                 "used when fitting a break-point.")

            if not self._stddev_flag:
                raise ValueError("'return_stddev' must be enabled when "
                                 "computing the radial power spectrum. "
                                 "The WLS fit requires uncertainties.")

            y_err = np.log10(self.ps1D_stddev[clip_func(self.freqs.value,
                                                        self.low_cut.value,
                                                        self.high_cut.value)])

        if brk is not None:
            # Try the fit with a break in it.
            if not log_break:
                brk = self._to_pixel_freq(brk).value
                brk = np.log10(brk)
            else:
                # A value given in log shouldn't have dimensions
                if hasattr(brk, "unit"):
                    assert brk.unit == u.dimensionless_unscaled
                    brk = brk.value

            brk_fit = \
                Lm_Seg(x, y, brk)
            brk_fit.fit_model(verbose=verbose)

            if brk_fit.params.size == 5:

                # Check to make sure this leaves enough to fit to.
                if sum(x < brk_fit.brk) < min_fits_pts:
                    warnings.warn("Not enough points to fit to." +
                                  " Ignoring break.")

                    self._brk = None
                else:
                    good_pts = x.copy() < brk_fit.brk
                    x = x[good_pts]
                    y = y[good_pts]

                    self._brk = 10**brk_fit.brk / u.pix
                    self._brk_err = np.log(10) * self.brk.value * \
                        brk_fit.brk_err / u.pix

                    self._slope = brk_fit.slopes
                    self._slope_err = brk_fit.slope_errs

                    self.fit = brk_fit.fit

            else:
                self._brk = None
                # Break fit failed, revert to normal model
                warnings.warn("Model with break failed, reverting to model\
                               without break.")
        else:
            self._brk = None
            self._brk_err = None

        if self.brk is None:
            x = sm.add_constant(x)

            if weighted_fit:
                model = sm.WLS(y, x, missing='drop', weights=1 / y_err**2)
            else:
                model = sm.OLS(y, x, missing='drop')

            self.fit = model.fit()

            self._slope = self.fit.params[1]
            self._slope_err = self.fit.bse[1]

    @property
    def slope(self):
        '''
        Power spectrum slope(s).
        '''
        return self._slope

    @property
    def slope_err(self):
        '''
        1-sigma error on the power spectrum slope(s).
        '''
        return self._slope_err

    @property
    def brk(self):
        '''
        Fitted break point.
        '''
        return self._brk

    @property
    def brk_err(self):
        '''
        1-sigma on the break point.
        '''
        return self._brk_err

    def apodizing_kernel(self, kernel_type="tukey", alpha=0.1, beta=0.0):
        '''
        Return an apodizing kernel to be applied to the image before taking
        Fourier transform

        Returns
        -------
        window : `~numpy.ndarray`
            Apodizing kernel
        '''

        if self.data is not None:
            shape = self.data.shape
        else:
            # MVC doesn't have a data attribute set
            shape = self.centroid.shape

        # Assume first axis is velocity if >2 dimensions
        if len(shape) > 2:
            shape = shape[1:]

        avail_types = ['splitcosinebell', 'hanning', 'tukey',
                       'cosinebell']

        if kernel_type == "splitcosinebell":
            return SplitCosineBellWindow(alpha, beta)(shape)
        elif kernel_type == "hanning":
            return HanningWindow()(shape)
        elif kernel_type == "tukey":
            return TukeyWindow(alpha)(shape)
        elif kernel_type == 'cosinebell':
            return CosineBellWindow(alpha)(shape)
        else:
            raise ValueError("kernel_type {0} is not one of the available "
                             "types: {1}".format(kernel_type, avail_types))

        return window

    def fit_2Dpspec(self, fit_method='LevMarq', p0=(), low_cut=None,
                    high_cut=None, bootstrap=True, niters=100,
                    use_azimmask=False, radial_weighting=False,
                    fix_ellip_params=False):
        '''
        Model the 2D power-spectrum surface with an elliptical power-law model.

        Parameters
        ----------
        fit_method : str, optional
            The algorithm fitting to use. Only 'LevMarq' is currently
            available.
        p0 : tuple, optional
            Initial parameters for fitting. If no values are given, the initial
            parameters start from the 1D fit parameters.
        low_cut : `~astropy.units.Quantity`, optional
            Lowest frequency to consider in the fit.
        high_cut : `~astropy.units.Quantity`, optional
            Highest frequency to consider in the fit.
        bootstrap : bool, optional
            Bootstrap using the model residuals to estimate the parameter
            standard errors. This tends to give more realistic intervals than
            the covariance matrix.
        niters : int, optional
            Number of bootstrap iterations.
        use_azimmask : bool, optional
            Use the azimuthal mask defined for the 1D spectrum, when azimuthal
            limit have been given.
        radial_weighting : bool, optional
            To account for the increasing number of samples at greater radii,
            the fit can be weighted by :math:`1/\mathrm{radius}` to emphasize the
            points at small radii. DO NOT enabled weighting when the field is
            elliptical! This will bias the fit parameters! Default is False.
        fix_ellip_params : bool, optional
            If the field is expected to be isotropic, the ellipticity and theta
            parameters can be fixed in the fit. This will help the fit since
            the isotropic case sits at the edge of the ellipticity parameter
            space and can be difficult to correctly converge to.
        '''

        # Make the data to fit to
        if low_cut is None:
            # Default to the largest frequency, since this is just 1 pixel
            # in the 2D PSpec.
            self.low_cut = 1. / (0.5 * float(max(self.ps2D.shape)) * u.pix)
        else:
            self.low_cut = self._to_pixel_freq(low_cut)

        if high_cut is None:
            self.high_cut = self.freqs.max().value / u.pix
        else:
            self.high_cut = self._to_pixel_freq(high_cut)

        yy_freq, xx_freq = make_radial_freq_arrays(self.ps2D.shape)

        freqs_dist = np.sqrt(yy_freq**2 + xx_freq**2)

        mask = clip_func(freqs_dist, self.low_cut.value, self.high_cut.value)

        if hasattr(self, "_azim_mask") and use_azimmask:
            mask = np.logical_and(mask, self._azim_mask)

        if not mask.any():
            raise ValueError("Limits have removed all points to fit. "
                             "Make low_cut and high_cut less restrictive.")

        if len(p0) == 0:
            if hasattr(self, 'slope'):
                if isinstance(self.slope, np.ndarray):
                    slope_guess = self.slope[0]
                else:
                    slope_guess = self.slope
                amp_guess = self.fit.params[0]
            else:
                # Let's guess it's going to be ~ -2
                slope_guess = -2.
                amp_guess = np.log10(np.nanmax(self.ps2D))

            # Use an initial guess pi / 2 for theta
            theta = np.pi / 2.
            # For ellip = 0.5
            ellip_conv = 0
            p0 = (amp_guess, ellip_conv, theta, slope_guess)

        params, stderrs, fit_2Dmodel, fitter = \
            fit_elliptical_powerlaw(np.log10(self.ps2D[mask]),
                                    xx_freq[mask],
                                    yy_freq[mask], p0,
                                    fit_method=fit_method,
                                    bootstrap=bootstrap,
                                    niters=niters,
                                    radial_weighting=radial_weighting,
                                    fix_ellip_params=fix_ellip_params)

        self.fit2D = fit_2Dmodel
        self._fitter = fitter

        self._slope2D = params[3]
        self._slope2D_err = stderrs[3]

        self._theta2D = params[2] % np.pi
        self._theta2D_err = stderrs[2]

        # Apply transforms to convert back to the [0, 1) ellipticity range
        self._ellip2D = inverse_interval_transform(params[1], 0, 1)
        self._ellip2D_err = \
            inverse_interval_transform_stderr(stderrs[1], params[1], 0, 1)

        # Add a warning that if ellip is close to 1 it may be worth fixing that
        # parameter.
        if self.ellip2D > 0.97:
            warnings.warn("The elliptical parameter is close to 1. The field "
                          "may be isotropic and the fit is not converging to "
                          "1. Consider fitting with `fix_ellip_params=True`,"
                          " which forces the ellipticity to 1.")

    @property
    def slope2D(self):
        '''
        Fitted slope of the 2D power spectrum.
        '''
        return self._slope2D

    @property
    def slope2D_err(self):
        '''
        Slope standard error of the 2D power spectrum.
        '''
        return self._slope2D_err

    @property
    def theta2D(self):
        '''
        Fitted position angle of the 2D power spectrum.
        '''
        return self._theta2D

    @property
    def theta2D_err(self):
        '''
        Position angle standard error of the 2D power spectrum.
        '''
        return self._theta2D_err

    @property
    def ellip2D(self):
        '''
        Fitted ellipticity of the 2D power spectrum.
        '''
        return self._ellip2D

    @property
    def ellip2D_err(self):
        '''
        Ellipticity standard error of the 2D power spectrum.
        '''
        return self._ellip2D_err

    def plot_fit(self, show=True, show_2D=False, color='r', fit_color=None,
                 label=None,
                 fillin_errs=True, symbol="D", xunit=u.pix**-1, save_name=None,
                 use_wavenumber=False):
        '''
        Plot the fitted model.

        Parameters
        ----------
        show : bool, optional
            Call `plt.show()` after plotting.
        show_2D : bool, optional
            Plot the 2D power spectrum with contours for the masked regions
            and 2D fit contours (if the 2D power spectrum was fit).
        color : str, optional
            Color to use in the plotted points.
        fit_color : str, optional
            Color to show the fitted relation in. Defaults to `color` when
            no color is given.
        label : str, optional
            Apply a label to the 1D plot. Useful for overplotting multiple
            power-spectra.
        fillin_errs : bool, optional
            Show the range of the standard deviation with as a transparent
            filled in region. When disabled, the standard deviations are shown
            as error bars.
        symbol : str, optional
            Plot symbols for the 1D power spectrum.
        xunit : `astropy.units.Unit`, optional
            Units for the x-axis. If a header is given, `xunit` can be given
            in inverse angular units. And if a distance is given, an inverse
            physical unit can also be passed.
        save_name : str, optional
            File name for the plot to be saved. Enables saving when a string
            is given.
        use_wavenumber : bool, optional
            Convert spatial frequencies to a wavenumber.
        '''

        import matplotlib.pyplot as p

        if use_wavenumber:
            xlab = r"k / (" + xunit.to_string() + ")"
        else:
            xlab = r"Spatial Frequency (" + xunit.to_string() + ")"

        if fit_color is None:
            fit_color = color

        # 2D Spectrum is shown alongside 1D. Otherwise only 1D is returned.
        if show_2D:
            yy_freq, xx_freq = make_radial_freq_arrays(self.ps2D.shape)

            freqs_dist = np.sqrt(yy_freq**2 + xx_freq**2)

            mask = np.logical_and(freqs_dist >= self.low_cut.value,
                                  freqs_dist <= self.high_cut.value)

            # Scale the colour map to be values within the mask
            vmax = np.log10(self.ps2D[mask]).max()
            vmin = np.log10(self.ps2D[mask]).min()

            p.subplot(122)
            p.imshow(np.log10(self.ps2D), interpolation="nearest",
                     origin="lower", vmax=vmax, vmin=vmin)
            cbar = p.colorbar()
            cbar.set_label(r"log $P_2 \ (K_x,\ K_y)$")

            p.contour(mask, colors=[color], linestyles='--')

            # Plot fit contours
            if hasattr(self, 'fit2D'):
                p.contour(self.fit2D(xx_freq, yy_freq), cmap='viridis')

            if hasattr(self, "_azim_mask"):
                p.contour(self._azim_mask, colors=[color], linestyles='--')

            ax = p.subplot(121)
        else:
            ax = p.subplot(111)

        good_interval = clip_func(self.freqs.value, self.low_cut.value,
                                  self.high_cut.value)

        y_fit = self.fit.fittedvalues
        fit_index = np.logical_and(np.isfinite(self.ps1D), good_interval)

        # Set the x-values to use (freqs or k)
        if use_wavenumber:
            xvals = self.wavenumbers
        else:
            xvals = self.freqs

        xvals = self._spatial_freq_unit_conversion(xvals, xunit).value

        if self._stddev_flag:

            # Axis limits to highlight the fitted region
            vmax = 1.1 * \
                np.max((self.ps1D + self.ps1D_stddev)
                       [self.freqs <= self.high_cut])

            logyerrs = 0.434 * (self.ps1D_stddev / self.ps1D)

            if fillin_errs:
                # Implementation by R. Boyden
                ax.fill_between(np.log10(xvals),
                                np.log10(self.ps1D) - logyerrs,
                                np.log10(self.ps1D) + logyerrs,
                                color=color,
                                alpha=0.5)

                ax.plot(np.log10(xvals), np.log10(self.ps1D), symbol,
                        color=color, markersize=5, alpha=0.8)

            else:
                ax.errorbar(np.log10(xvals),
                            np.log10(self.ps1D),
                            yerr=logyerrs,
                            color=color,
                            fmt=symbol, markersize=5, alpha=0.5, capsize=10,
                            elinewidth=3)

            ax.plot(np.log10(xvals[fit_index]), y_fit, linestyle='-',
                    label=label, linewidth=3, color=fit_color)
            ax.set_xlabel("log " + xlab)
            ax.set_ylabel(r"log P$_2(K)$")

            ax.set_ylim(top=np.log10(vmax))

        else:
            vmax = 1.1 * np.max(self.ps1D[self.freqs <= self.high_cut])

            ax.loglog(self.xvals, 10**y_fit, linestyle='-',
                      label=label, linewidth=2, color=fit_color)

            ax.loglog(self.xvals, self.ps1D, symbol, alpha=0.5,
                      markersize=5, color=color)

            ax.set_xlabel(xlab)
            ax.set_ylabel(r"P$_2(K)$")

            ax.set_ylim(top=vmax)

        # Show the fitting extents
        low_cut = self._spatial_freq_unit_conversion(self.low_cut, xunit).value
        high_cut = \
            self._spatial_freq_unit_conversion(self.high_cut, xunit).value
        low_cut = low_cut if not use_wavenumber else \
            low_cut * min(self._ps2D.shape)
        high_cut = high_cut if not use_wavenumber else \
            high_cut * min(self._ps2D.shape)
        p.axvline(np.log10(low_cut), color=color, alpha=0.5, linestyle='--')
        p.axvline(np.log10(high_cut), color=color, alpha=0.5, linestyle='--')

        p.grid(True)

        if save_name is not None:
            p.savefig(save_name)

        if show:
            p.show()
