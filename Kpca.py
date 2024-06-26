import numpy as np
from scipy.linalg import eigh

class kPCA:
    """
    Parameters
    ----------
    kernel : string, optional (default='rbf')
         Specifies the kernel type to be used in the algorithm.
         It must be one of 'poly' or 'rbf'
         If none is given, 'rbf' will be used.

    sigma : float, optional (default=1)
        Kernel coefficient for 'rbf'

    order : int, optional (default=3)
        Kernel degree for 'poly'

    q : int, optional (default='same')
        number of retained eigenvectors (alphas) for the reconstruction error
        If q is 'auto' then n_features will be used instead. For a 'linear
        kernel this will result in zero reconstruction error

    sample_pct : float, optional (default: 1.0)
        What percentage of the data to use to determine the principle components

    batch_size : int, optional (default: 500)
        The number of examples per batch during testing

    contamination : float in (0., 0.5), optional (default=0.1)
        The amount of contamination of the data set,
        i.e. the proportion of outliers in the data set. Used when fitting to
        define the threshold on the decision function.

    verbose : bool, (default: False)
        Prints out runtime and feedback

    useAll : bool, (default = True )
        #Use the full dataset for the evaluation projection?

    Attributes
    ----------

    model_X_S : numpy array of shape (n_sub,d_features)
        sample of X used for calulating alphas, typically the full sample is \
        used so that X_S = X. Sampling set by sample_pct

    model_K_mat : numpy array of shape (n_sub,sub)
        uncentered gram matrix after training

    model_alphas : numpy array of shape (n_samples, q)
        retained eigen values after training

    decision_scores_ : numpy array of shape (n_samples,)
        The outlier scores of the training data.
        The higher, the more abnormal. Outliers tend to have higher scores.
        This value is available once the detector is fitted.

    threshold_ : float
        The threshold is based on ``contamination``. It is the
        ``n_samples * contamination`` most abnormal samples in
        ``decision_scores_``. The threshold is calculated for generating
        binary outlier labels.

    labels_ : int, either 0 or 1
        The binary labels of the training data. 0 stands for inliers
        and 1 for outliers/anomalies. It is generated by applying
        ``threshold_`` on ``decision_scores_``.
    """

    def __init__(self, order = 3, q = 'same', sigma = 1.0,
                 sample_pct = 1.0, shrinking=True, batch_size = 500,
                 contamination = 0.1, verbose=False):
        self.sigma = sigma
        self.gamma = 1/2/sigma/sigma
        self.order = order
        self.q = q
        self.sample_pct = sample_pct
        self.batch_size = batch_size
        self.contamination = contamination
        self.verbose = verbose


    def subsample_data(self,X, sample_pct = None):
        """Returns X_S a random subsample of X".

        Parameters
        ----------
        X : numpy array of shape (n_samples, d_features)
            The input samples.
        sample_pct: float, percentage (0,1) to sample from X
        """

        n_sub = int(sample_pct * X.shape[0])

        sample_idx = np.random.permutation(n_sub)

        X_s = X[sample_idx]

        return X_s


    def gramMatrix(self,X, X_S, params = None):
        """Returns the (n x n) gram matrix based on the kernel.

        Parameters
        ----------
        X : numpy array of shape (n_samples, d_features)
            The input samples.

        kernel: string,  {'rbf, 'poly'}
            kernel function to use options

        params: float, kernel parameter, defaults to sigma or order if None
        """


        a = np.expand_dims(np.diag(X_S.dot(X_S.T)),axis = 1).dot(np.ones((1, X.shape[0])))
        b = np.ones((X_S.shape[0],1)).dot(np.expand_dims(np.diag(X.dot(X.T)),axis = 0))
    
        sqrd_dists = a + b - 2*X_S.dot(X.T)

        # RBF
        params = self.gamma
        K = np.exp(-params*sqrd_dists)

        # Poly
        #params = self.order
        #K = np.power((sqrd_dists +1),params)
        return K



    def eigenDecomp_gramMatrix(self, K_centered):
        """Returns the leading q number of eigenvectors from the eigendecomposition
        of the centered gram matrix

        Parameters
        ----------
        K : numpy array of shape (n_samples,n_samples)
            centered gram matrix

        numev: int, number of eigenvectors (alphas) to retain
        """
        from scipy.linalg import eigh

        numev = self.q #use class default if none is specified

        w, v = eigh(K_centered)
        w = w.reshape(-1,1)
        w = np.flipud(w)
        v = np.fliplr(v)
        alphas = v[:,:numev]

        #Each column is an eigen vector
        lambdas = w[:numev]
        #from biggest to smallest
        alphs = alphas*np.squeeze(1/np.sqrt(lambdas))



        return alphs


    def calc_reconstructionErrors(self, X,  X_S, K_mat, alphs):
        """Returns the reconstruction error projecting onto alphas.

        Parameters
        ----------
        X : numpy array of shape (n_samples, d_features)
            The input samples.

        alphs: numpy array of shape (n_samples, q)
            eigenvectors of centered gram matrix


        X_S : numpy array of shape (n_subsamples, d_features), optional (default=None)
            Subsampling of the data. If none, the full kernel is used for projection
        """



        n_samples, d_features = X.shape
        n_sub = X_S.shape[0]

        numev = alphs.shape[1]


        #helper calcs
        Krow = K_mat.sum(axis = 0)/n_sub #not normed!
        Ksum = (Krow).sum()/n_sub
        sumalphs = np.ones(X_S.shape[0]).dot(alphs)


        reconstruction_errs = np.zeros(n_samples)

        for block_i in (range(0,n_samples,self.batch_size)):
            if self.verbose:
                percentDone = 100 * (block_i)/ n_samples;
                print(f"Evaluating training set... {percentDone:.2f}%", end='\r')


            X_block = X[block_i:block_i+self.batch_size,:]
            n_block = X_block.shape[0]

            k_L = self.gramMatrix(X_block, X_S)


            f_L = np.dot(k_L.T,alphs) - (sumalphs*np.ones((n_block,numev)) * \
                         np.expand_dims((np.sum(k_L,axis=0).T/n_sub - Ksum),axis=1)) \
                         -  np.ones((n_block, numev))*np.dot(Krow,alphs)
            

            errs_block = ( 1 - (2*np.sum(k_L,axis = 0)/n_sub).T + Ksum ) \
                    - np.diag(np.dot(f_L,f_L.T))


            # f_L2 = np.dot(k_L.T, alphs) - (sumalphs * np.expand_dims((np.sum(k_L, axis=0)/n_sub - Ksum), axis=0)) - np.dot(Krow, alphs)
            # errs_block2 = 1 - (2 * np.sum(k_L, axis=0)/n_sub) + Ksum - np.sum(f_L * f_L, axis=0)
            
            reconstruction_errs[block_i:block_i+self.batch_size] = errs_block


        if self.verbose:
            print(f"Evaluating training set... {100:.2f}%")
        return  reconstruction_errs

    def threshold(self,scores,contamination):
        """Fit detector. y is optional for unsupervised methods.

        Parameters
        ----------
        scores : numpy array of shape (n_samples, d_features)
        The input samples.

        contamination : float in (0., 0.5), optional (default=0.1)
            The amount of contamination of the data set,
            i.e. the proportion of outliers in the data set. Used when fitting to
            define the threshold on the decision function.
        """
        threshold_ = np.quantile(scores,1-contamination)
        labels = np.ones(scores.shape[0])
        labels[scores < threshold_] = 0

        self.threshold_ = threshold_
        return labels



    def fit(self, X, y=None):
        """Fit detector. y is optional for unsupervised methods.

        Parameters
        ----------
        X : numpy array of shape (n_samples, d_features)
        The input samples.

        y : numpy array of shape (n_samples,), optional (default=None)
        The ground truth of the input samples (labels).
        """

        n_samples, d_features = np.shape(X)
        self.d_features = d_features

        if int(self.sample_pct * X.shape[0]) < self.d_features:
            self.n_sub = max(self.q,self.d_features)
            self.sample_pct = (self.n_sub/X.shape[0])+1e-3


        if self.sample_pct < 1:
            X_S = self.subsample_data(X)
        else:
            X_S = X


        n_sub = X_S.shape[0]

        K_mat = self.gramMatrix(X_S,X_S)


        # symmetrize to correct minor numerical errors
        K_mat = (K_mat + K_mat.T) / 2

        #helper calcs
        Krow = K_mat.sum(axis = 0)/n_sub #not normed!
        Ksum = (Krow).sum()/n_sub
        K_centered = np.zeros_like(K_mat)
        # Looping over each element
        for i in range(K_mat.shape[0]):    # Loop over rows
            for j in range(K_mat.shape[1]):  # Loop over columns
                K_centered[i][j] = K_mat[i][j] - Krow[i] - Krow[j] + Ksum


        # one_n = np.ones((n_sub,n_sub)) / n_sub
        # K_centered2 = K_mat - one_n.dot(K_mat - K_mat.dot(one_n)) + one_n.dot(K_mat).dot(one_n)

        if self.verbose:
            print("Computed gram matrix")

        alphs = self.eigenDecomp_gramMatrix(K_centered)

        if self.verbose:
                print("Computed alphas","\n")

        self.model_alphas = alphs
        self.model_X_S = X_S
        self.model_K_mat = K_mat

        reconstruction_errs = self.calc_reconstructionErrors(X,  X_S, K_mat, alphs)

        self.decision_scores_ = reconstruction_errs

        self.labels_ = self.threshold(self.decision_scores_,self.contamination)

        return self



    def decision_function(self, X_test):
        """predict anomaly scores (reconstruction error) using model \
        gram matrix and alphas

        Parameters
        ----------
        X_test : numpy array of shape (n_test_samples, d_features)
        The test samples.
        """

        if X_test.ndim == 1: # correct dimension if a single example is given
            X_test = np.expand_dims(X_test,axis = 0)

        scores = self.calc_reconstructionErrors(X_test,  self.model_X_S, self.model_K_mat, self.model_alphas)

        return scores


    def predict(self,X_test,threshold = None):
        """predict anomaly label (reconstruction error) using model \
        gram matrix and alphas

        Parameters
        ----------
        X_test : numpy array of shape (n_test_samples, d_features)
        The test samples.

        threshold: float, optional, default to threshold calculated by .fit()
        """

        if X_test.ndim == 1: # correct dimension if a single example is given
            X_test = np.expand_dims(X_test,axis = 0)

        if threshold == None:
            threshold = self.threshold_

        scores = self.predict(X_test)

        labels = np.ones(scores.shape[0])
        labels[scores < threshold] = 0

        return labels


