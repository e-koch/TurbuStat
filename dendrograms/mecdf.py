'''

Implementation of a Multivariable ECDF

Limited to step function for now.

'''

import numpy as np
from statsmodels.distributions import ECDF

def mecdf(arr):
    '''

    Parameters
    **********

    arr : np.ndarray
          Array containing where each row is a PDF.

    Output
    ******

    ecdf - np.ndarray
           Array containing the ECDF of each row.

    '''
    assert isinstance(arr, np.ndarray)

    nrows = arr.shape[0]
    ncol = arr.shape[1]
    ecdf = np.empty(arr.shape)

    for n in range(nrows):
        ecdf[n,:] = np.cumsum(arr[n,:]/np.sum(arr[n,:].astype(float)))

    return ecdf


