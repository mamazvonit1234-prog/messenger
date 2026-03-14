// Rokomax Messenger - Authentication Module

// ==================== AUTH STATE ====================

const AuthState = {
    isAuthenticated: false,
    user: null,
    token: null,
    twoFactorRequired: false,
    tempToken: null,
    loginAttempts: 0,
    lastLoginAttempt: null
};

// ==================== INITIALIZATION ====================

document.addEventListener('DOMContentLoaded', () => {
    initializeAuth();
});

function initializeAuth() {
    // Check for existing session
    checkExistingSession();

    // Initialize auth tabs
    initializeAuthTabs();

    // Initialize form validation
    initializeFormValidation();

    // Initialize password strength checker
    initializePasswordStrength();

    // Initialize social login buttons
    initializeSocialLogin();
}

// ==================== SESSION MANAGEMENT ====================

async function checkExistingSession() {
    const token = localStorage.getItem('rokomax_token');
    const userData = localStorage.getItem('rokomax_user');

    if (token && userData) {
        try {
            // Verify token with server
            const response = await api.get('/auth/verify');

            if (response.valid) {
                AuthState.isAuthenticated = true;
                AuthState.token = token;
                AuthState.user = JSON.parse(userData);

                // Redirect to main app
                window.location.href = '/app';
                return;
            }
        } catch (error) {
            console.error('Session verification failed:', error);
            clearSession();
        }
    }

    // Show login form
    showLoginForm();
}

function clearSession() {
    localStorage.removeItem('rokomax_token');
    localStorage.removeItem('rokomax_user');
    AuthState.isAuthenticated = false;
    AuthState.user = null;
    AuthState.token = null;
}

// ==================== AUTH TABS ====================

function initializeAuthTabs() {
    const tabs = document.querySelectorAll('.auth-tab');
    const forms = document.querySelectorAll('.auth-form');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.dataset.tab;

            // Update tabs
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            // Update forms
            forms.forEach(form => {
                form.classList.remove('active');
                if (form.id === target + 'Form') {
                    form.classList.add('active');
                }
            });

            // Reset forms
            resetForms();
        });
    });
}

function resetForms() {
    document.getElementById('loginForm').reset();
    document.getElementById('registerForm').reset();

    // Clear validation states
    document.querySelectorAll('.form-control').forEach(input => {
        input.classList.remove('error', 'success');
    });

    // Clear password strength
    resetPasswordStrength();
}

// ==================== LOGIN ====================

async function handleLogin(event) {
    event.preventDefault();

    const email = document.getElementById('loginEmail').value;
    const password = document.getElementById('loginPassword').value;
    const rememberMe = document.getElementById('rememberMe').checked;

    // Validate inputs
    if (!validateEmail(email)) {
        showInputError('loginEmail', 'Please enter a valid email');
        return;
    }

    if (!password) {
        showInputError('loginPassword', 'Please enter your password');
        return;
    }

    // Check rate limiting
    if (!checkRateLimit()) {
        showToast('Too many login attempts. Please try again later.', 'error');
        return;
    }

    // Show loading state
    const loginButton = document.getElementById('loginButton');
    loginButton.classList.add('loading');

    try {
        const response = await api.post('/auth/login', {
            email,
            password,
            rememberMe
        });

        if (response.twoFactorRequired) {
            // Show 2FA form
            AuthState.tempToken = response.tempToken;
            showTwoFactorForm();
        } else {
            // Login successful
            handleLoginSuccess(response);
        }

    } catch (error) {
        console.error('Login failed:', error);

        // Update login attempts
        AuthState.loginAttempts++;
        AuthState.lastLoginAttempt = Date.now();

        if (error.message.includes('verify email')) {
            showVerificationNotice(email);
        } else {
            showToast(error.message || 'Login failed. Please try again.', 'error');
        }

    } finally {
        loginButton.classList.remove('loading');
    }
}

function handleLoginSuccess(response) {
    // Save auth data
    AuthState.isAuthenticated = true;
    AuthState.token = response.token;
    AuthState.user = response.user;

    localStorage.setItem('rokomax_token', response.token);
    localStorage.setItem('rokomax_user', JSON.stringify(response.user));

    // Show success message
    showToast('Login successful!', 'success');

    // Redirect to main app
    setTimeout(() => {
        window.location.href = '/app';
    }, 1000);
}

function checkRateLimit() {
    const maxAttempts = 5;
    const timeWindow = 15 * 60 * 1000; // 15 minutes

    if (AuthState.lastLoginAttempt &&
        Date.now() - AuthState.lastLoginAttempt < timeWindow &&
        AuthState.loginAttempts >= maxAttempts) {
        return false;
    }

    // Reset counter if outside time window
    if (AuthState.lastLoginAttempt &&
        Date.now() - AuthState.lastLoginAttempt > timeWindow) {
        AuthState.loginAttempts = 0;
    }

    return true;
}

// ==================== REGISTRATION ====================

async function handleRegister(event) {
    event.preventDefault();

    const formData = {
        firstName: document.getElementById('registerFirstName').value,
        lastName: document.getElementById('registerLastName').value,
        email: document.getElementById('registerEmail').value,
        phone: document.getElementById('registerPhone').value,
        username: document.getElementById('registerUsername').value,
        password: document.getElementById('registerPassword').value,
        confirmPassword: document.getElementById('registerConfirmPassword').value
    };

    // Validate all fields
    if (!validateRegistration(formData)) {
        return;
    }

    // Check terms agreement
    if (!document.getElementById('termsAgree').checked) {
        showToast('You must agree to the terms and conditions', 'error');
        return;
    }

    // Show loading state
    const registerButton = document.getElementById('registerButton');
    registerButton.classList.add('loading');

    try {
        const response = await api.post('/auth/register', formData);

        if (response.requiresVerification) {
            // Show email verification notice
            showVerificationNotice(formData.email);
        } else {
            // Auto-login after registration
            handleLoginSuccess(response);
        }

    } catch (error) {
        console.error('Registration failed:', error);

        if (error.errors) {
            // Display validation errors
            Object.keys(error.errors).forEach(field => {
                showInputError(`register${capitalize(field)}`, error.errors[field]);
            });
        } else {
            showToast(error.message || 'Registration failed. Please try again.', 'error');
        }

    } finally {
        registerButton.classList.remove('loading');
    }
}

function validateRegistration(data) {
    let isValid = true;

    // First name validation
    if (!data.firstName || data.firstName.length < 2) {
        showInputError('registerFirstName', 'First name must be at least 2 characters');
        isValid = false;
    }

    // Email validation
    if (!validateEmail(data.email)) {
        showInputError('registerEmail', 'Please enter a valid email');
        isValid = false;
    }

    // Phone validation
    if (!validatePhone(data.phone)) {
        showInputError('registerPhone', 'Please enter a valid phone number');
        isValid = false;
    }

    // Username validation
    if (!validateUsername(data.username)) {
        showInputError('registerUsername', 'Username must be 3-20 characters and contain only letters, numbers, and underscores');
        isValid = false;
    }

    // Password validation
    const passwordValidation = validatePassword(data.password);
    if (!passwordValidation.valid) {
        showInputError('registerPassword', passwordValidation.message);
        isValid = false;
    }

    // Password match validation
    if (data.password !== data.confirmPassword) {
        showInputError('registerConfirmPassword', 'Passwords do not match');
        isValid = false;
    }

    return isValid;
}

// ==================== TWO-FACTOR AUTH ====================

function showTwoFactorForm() {
    document.querySelector('.auth-tabs').style.display = 'none';
    document.querySelectorAll('.auth-form').forEach(form => {
        form.style.display = 'none';
    });
    document.getElementById('twoFactorAuth').style.display = 'block';

    // Focus first input
    document.querySelector('.otp-input').focus();
}

async function verify2FA() {
    const inputs = document.querySelectorAll('.otp-input');
    const code = Array.from(inputs).map(input => input.value).join('');

    if (code.length !== 6) {
        showToast('Please enter the 6-digit code', 'error');
        return;
    }

    try {
        const response = await api.post('/auth/verify-2fa', {
            tempToken: AuthState.tempToken,
            code: code
        });

        handleLoginSuccess(response);

    } catch (error) {
        console.error('2FA verification failed:', error);
        showToast(error.message || 'Invalid verification code', 'error');

        // Clear inputs
        inputs.forEach(input => input.value = '');
        inputs[0].focus();
    }
}

function moveToNext(input, index) {
    // Auto move to next input
    if (input.value.length === 1 && index < 5) {
        document.querySelectorAll('.otp-input')[index + 1].focus();
    }

    // Handle backspace
    if (input.value.length === 0 && index > 0) {
        document.querySelectorAll('.otp-input')[index - 1].focus();
    }
}

async function resend2FACode() {
    try {
        await api.post('/auth/resend-2fa', {
            tempToken: AuthState.tempToken
        });

        showToast('Verification code resent', 'success');

    } catch (error) {
        console.error('Failed to resend code:', error);
        showToast('Failed to resend code', 'error');
    }
}

// ==================== FORGOT PASSWORD ====================

function showForgotPassword() {
    // TODO: Implement forgot password modal
    showToast('Password reset feature coming soon', 'info');
}

async function resetPassword(email) {
    try {
        await api.post('/auth/reset-password', { email });
        showToast('Password reset email sent', 'success');

    } catch (error) {
        console.error('Password reset failed:', error);
        showToast('Failed to send reset email', 'error');
    }
}

// ==================== EMAIL VERIFICATION ====================

function showVerificationNotice(email) {
    const authBox = document.querySelector('.auth-box');
    authBox.innerHTML = `
        <div class="auth-header">
            <img src="/assets/images/logo.svg" alt="Rokomax" class="auth-logo">
            <h1 class="auth-title">Verify Your Email</h1>
            <p class="auth-subtitle">We've sent a verification link to ${email}</p>
        </div>

        <div class="verification-notice">
            <i class="fas fa-envelope-open-text"></i>
            <p>Please check your email and click the verification link to activate your account.</p>
            <p class="small">Didn't receive the email? <a href="#" onclick="resendVerification('${email}')">Click here to resend</a></p>
        </div>
    `;
}

async function resendVerification(email) {
    try {
        await api.post('/auth/resend-verification', { email });
        showToast('Verification email resent', 'success');

    } catch (error) {
        console.error('Failed to resend verification:', error);
        showToast('Failed to resend verification email', 'error');
    }
}

async function verifyEmail(token) {
    try {
        await api.post('/auth/verify-email', { token });
        showToast('Email verified successfully! You can now log in.', 'success');

        // Show login form
        showLoginForm();

    } catch (error) {
        console.error('Email verification failed:', error);
        showToast('Email verification failed', 'error');
    }
}

// ==================== PASSWORD STRENGTH ====================

function initializePasswordStrength() {
    const passwordInput = document.getElementById('registerPassword');

    passwordInput.addEventListener('input', () => {
        checkPasswordStrength(passwordInput.value);
        checkPasswordMatch();
    });
}

function checkPasswordStrength(password) {
    const requirements = {
        length: password.length >= 8,
        uppercase: /[A-Z]/.test(password),
        lowercase: /[a-z]/.test(password),
        number: /[0-9]/.test(password),
        special: /[!@#$%^&*(),.?":{}|<>]/.test(password)
    };

    // Update requirement indicators
    Object.keys(requirements).forEach(req => {
        const element = document.querySelector(`[data-req="${req}"]`);
        if (element) {
            element.classList.toggle('met', requirements[req]);
            element.innerHTML = (requirements[req] ? '✅' : '❌') + element.innerHTML.slice(2);
        }
    });

    // Update strength bars
    const strengthCount = Object.values(requirements).filter(Boolean).length;
    const bars = document.querySelectorAll('.strength-bar');

    bars.forEach((bar, index) => {
        bar.classList.remove('weak', 'medium', 'strong');
        if (index < strengthCount) {
            if (strengthCount <= 2) {
                bar.classList.add('weak');
            } else if (strengthCount <= 4) {
                bar.classList.add('medium');
            } else {
                bar.classList.add('strong');
            }
        }
    });
}

function checkPasswordMatch() {
    const password = document.getElementById('registerPassword').value;
    const confirm = document.getElementById('registerConfirmPassword').value;
    const matchIndicator = document.getElementById('passwordMatch');

    if (confirm) {
        if (password === confirm) {
            matchIndicator.innerHTML = '✅ Passwords match';
            matchIndicator.style.color = 'var(--success-color)';
        } else {
            matchIndicator.innerHTML = '❌ Passwords do not match';
            matchIndicator.style.color = 'var(--danger-color)';
        }
    }
}

function resetPasswordStrength() {
    const requirements = document.querySelectorAll('.requirement');
    requirements.forEach(req => {
        req.classList.remove('met');
        req.innerHTML = '❌ ' + req.innerHTML.slice(2);
    });

    const bars = document.querySelectorAll('.strength-bar');
    bars.forEach(bar => {
        bar.classList.remove('weak', 'medium', 'strong');
    });

    document.getElementById('passwordMatch').innerHTML = '❌ Passwords do not match';
}

// ==================== SOCIAL LOGIN ====================

function initializeSocialLogin() {
    // Initialize OAuth providers
    initializeGoogleLogin();
    initializeGithubLogin();
}

function initializeGoogleLogin() {
    // Load Google Identity Services
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    document.head.appendChild(script);
}

function initializeGithubLogin() {
    // GitHub OAuth configuration
    const githubClientId = 'YOUR_GITHUB_CLIENT_ID';
    const redirectUri = window.location.origin + '/auth/github/callback';

    window.githubLogin = () => {
        const url = `https://github.com/login/oauth/authorize?client_id=${githubClientId}&redirect_uri=${redirectUri}&scope=user:email`;
        window.location.href = url;
    };
}

async function socialLogin(provider) {
    try {
        switch (provider) {
            case 'google':
                await handleGoogleLogin();
                break;
            case 'github':
                await handleGithubLogin();
                break;
            default:
                console.error('Unknown provider:', provider);
        }
    } catch (error) {
        console.error(`${provider} login failed:`, error);
        showToast(`${provider} login failed`, 'error');
    }
}

async function handleGoogleLogin() {
    // Initialize Google One Tap
    google.accounts.id.initialize({
        client_id: 'YOUR_GOOGLE_CLIENT_ID',
        callback: handleGoogleCredential
    });

    // Prompt user to select account
    google.accounts.id.prompt();
}

async function handleGoogleCredential(response) {
    try {
        const result = await api.post('/auth/google', {
            credential: response.credential
        });

        handleLoginSuccess(result);

    } catch (error) {
        console.error('Google login failed:', error);
        showToast('Google login failed', 'error');
    }
}

async function handleGithubLogin() {
    // GitHub OAuth is handled via redirect
    window.githubLogin();
}

// ==================== VALIDATION FUNCTIONS ====================

function validateEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

function validatePhone(phone) {
    const re = /^[\+]?[(]?[0-9]{3}[)]?[-\s\.]?[0-9]{3}[-\s\.]?[0-9]{4,6}$/;
    return re.test(phone);
}

function validateUsername(username) {
    const re = /^[a-zA-Z0-9_]{3,20}$/;
    return re.test(username);
}

function validatePassword(password) {
    const requirements = {
        length: password.length >= 8,
        uppercase: /[A-Z]/.test(password),
        lowercase: /[a-z]/.test(password),
        number: /[0-9]/.test(password),
        special: /[!@#$%^&*(),.?":{}|<>]/.test(password)
    };

    const strengthCount = Object.values(requirements).filter(Boolean).length;

    if (strengthCount < 3) {
        return {
            valid: false,
            message: 'Password is too weak'
        };
    }

    return {
        valid: true,
        message: 'Password is strong'
    };
}

function showInputError(inputId, message) {
    const input = document.getElementById(inputId);
    input.classList.add('error');

    // Show error message
    const errorDiv = document.createElement('div');
    errorDiv.className = 'input-error';
    errorDiv.textContent = message;

    // Remove existing error
    const existingError = input.parentNode.querySelector('.input-error');
    if (existingError) {
        existingError.remove();
    }

    input.parentNode.appendChild(errorDiv);

    // Remove error on input
    input.addEventListener('input', () => {
        input.classList.remove('error');
        const error = input.parentNode.querySelector('.input-error');
        if (error) {
            error.remove();
        }
    }, { once: true });
}

// ==================== PASSWORD VISIBILITY ====================

function togglePassword(inputId) {
    const input = document.getElementById(inputId);
    const button = input.parentNode.querySelector('.password-toggle i');

    if (input.type === 'password') {
        input.type = 'text';
        button.classList.remove('fa-eye');
        button.classList.add('fa-eye-slash');
    } else {
        input.type = 'password';
        button.classList.remove('fa-eye-slash');
        button.classList.add('fa-eye');
    }
}

// ==================== UTILITY FUNCTIONS ====================

function capitalize(string) {
    return string.charAt(0).toUpperCase() + string.slice(1);
}

function showLoginForm() {
    const authContainer = document.getElementById('authContainer');
    authContainer.style.display = 'flex';

    // Reset to login tab
    document.querySelector('[data-tab="login"]').click();

    // Clear any verification notices
    const authBox = document.querySelector('.auth-box');
    authBox.innerHTML = `
        <div class="auth-header">
            <img src="/assets/images/logo.svg" alt="Rokomax" class="auth-logo">
            <h1 class="auth-title">Rokomax</h1>
            <p class="auth-subtitle">Connect with friends and family</p>
        </div>

        <div class="auth-tabs">
            <button class="auth-tab active" data-tab="login">Login</button>
            <button class="auth-tab" data-tab="register">Register</button>
        </div>

        <!-- Login Form -->
        <form class="auth-form active" id="loginForm" onsubmit="handleLogin(event)">
            <div class="form-group">
                <label for="loginEmail">
                    <i class="fas fa-envelope"></i>
                    Email
                </label>
                <input type="email" id="loginEmail" class="form-control" placeholder="Enter your email" required>
            </div>

            <div class="form-group">
                <label for="loginPassword">
                    <i class="fas fa-lock"></i>
                    Password
                </label>
                <div class="password-input-wrapper">
                    <input type="password" id="loginPassword" class="form-control" placeholder="Enter password" required>
                    <button type="button" class="password-toggle" onclick="togglePassword('loginPassword')">
                        <i class="far fa-eye"></i>
                    </button>
                </div>
            </div>

            <div class="form-options">
                <label class="checkbox-label">
                    <input type="checkbox" class="checkbox" id="rememberMe">
                    <span class="checkbox-custom"></span>
                    Remember me
                </label>
                <a href="#" class="forgot-password" onclick="showForgotPassword()">Forgot password?</a>
            </div>

            <button type="submit" class="auth-button" id="loginButton">
                <span class="button-text">Login</span>
                <div class="button-loader"></div>
            </button>
        </form>

        <!-- Register Form -->
        <form class="auth-form" id="registerForm" onsubmit="handleRegister(event)">
            <div class="form-row">
                <div class="form-group half">
                    <label for="registerFirstName">First Name</label>
                    <input type="text" id="registerFirstName" class="form-control" placeholder="First name" required>
                </div>
                <div class="form-group half">
                    <label for="registerLastName">Last Name</label>
                    <input type="text" id="registerLastName" class="form-control" placeholder="Last name">
                </div>
            </div>

            <div class="form-group">
                <label for="registerEmail">Email</label>
                <input type="email" id="registerEmail" class="form-control" placeholder="Enter your email" required>
            </div>

            <div class="form-group">
                <label for="registerPhone">Phone</label>
                <input type="tel" id="registerPhone" class="form-control" placeholder="+1 (555) 000-0000" required>
            </div>

            <div class="form-group">
                <label for="registerUsername">Username</label>
                <input type="text" id="registerUsername" class="form-control" placeholder="@username" required>
            </div>

            <div class="form-group">
                <label for="registerPassword">Password</label>
                <div class="password-input-wrapper">
                    <input type="password" id="registerPassword" class="form-control" placeholder="Create password" required>
                    <button type="button" class="password-toggle" onclick="togglePassword('registerPassword')">
                        <i class="far fa-eye"></i>
                    </button>
                </div>
                <div class="password-strength" id="passwordStrength">
                    <div class="strength-bar"></div>
                    <div class="strength-bar"></div>
                    <div class="strength-bar"></div>
                    <div class="strength-bar"></div>
                </div>
            </div>

            <div class="form-group">
                <label for="registerConfirmPassword">Confirm Password</label>
                <div class="password-input-wrapper">
                    <input type="password" id="registerConfirmPassword" class="form-control" placeholder="Confirm password" required>
                </div>
                <div class="password-match" id="passwordMatch">❌ Passwords do not match</div>
            </div>

            <div class="form-group">
                <label class="checkbox-label">
                    <input type="checkbox" class="checkbox" id="termsAgree" required>
                    <span class="checkbox-custom"></span>
                    I agree to the <a href="#" onclick="showTerms()">Terms of Service</a> and
                    <a href="#" onclick="showPrivacy()">Privacy Policy</a>
                </label>
            </div>

            <button type="submit" class="auth-button" id="registerButton">
                <span class="button-text">Register</span>
                <div class="button-loader"></div>
            </button>
        </form>

        <!-- 2FA Form -->
        <div class="two-factor-auth" id="twoFactorAuth" style="display: none;">
            <h3>Two-Factor Authentication</h3>
            <p>Enter the code from your authenticator app</p>
            <div class="otp-inputs">
                <input type="text" maxlength="1" class="otp-input" onkeyup="moveToNext(this, 0)">
                <input type="text" maxlength="1" class="otp-input" onkeyup="moveToNext(this, 1)">
                <input type="text" maxlength="1" class="otp-input" onkeyup="moveToNext(this, 2)">
                <input type="text" maxlength="1" class="otp-input" onkeyup="moveToNext(this, 3)">
                <input type="text" maxlength="1" class="otp-input" onkeyup="moveToNext(this, 4)">
                <input type="text" maxlength="1" class="otp-input" onkeyup="moveToNext(this, 5)">
            </div>
            <button class="verify-2fa" onclick="verify2FA()">Verify</button>
            <a href="#" class="resend-code" onclick="resend2FACode()">Resend code</a>
        </div>
    `;

    // Reinitialize auth tabs and validation
    initializeAuthTabs();
    initializePasswordStrength();
}

// ==================== TERMS & PRIVACY ====================

function showTerms() {
    // TODO: Implement terms modal
    showToast('Terms of Service will be available soon', 'info');
}

function showPrivacy() {
    // TODO: Implement privacy modal
    showToast('Privacy Policy will be available soon', 'info');
}

// ==================== EXPORT ====================

// Make functions globally available
window.handleLogin = handleLogin;
window.handleRegister = handleRegister;
window.togglePassword = togglePassword;
window.showForgotPassword = showForgotPassword;
window.socialLogin = socialLogin;
window.verify2FA = verify2FA;
window.moveToNext = moveToNext;
window.resend2FACode = resend2FACode;
window.showTerms = showTerms;
window.showPrivacy = showPrivacy;
// Rokomax Messenger - Authentication Middleware

const jwt = require('jsonwebtoken');
const User = require('../models/User');

const auth = async (req, res, next) => {
    try {
        const token = req.header('Authorization')?.replace('Bearer ', '');

        if (!token) {
            throw new Error();
        }

        const decoded = jwt.verify(token, process.env.JWT_SECRET || 'your-secret-key');

        const user = await User.findById(decoded.userId);

        if (!user) {
            throw new Error();
        }

        req.user = decoded;
        req.userId = decoded.userId;
        next();
    } catch (error) {
        res.status(401).json({ error: 'Please authenticate' });
    }
};

module.exports = auth;