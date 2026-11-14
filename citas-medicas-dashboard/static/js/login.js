/**
 * login.js
 * Maneja el flujo de dos pasos: (1) credenciales, (2) código 2FA si aplica.
 */

const formLogin = document.getElementById("form-login");
const form2fa = document.getElementById("form-2fa");
const loginError = document.getElementById("login-error");
const tokenError = document.getElementById("token-error");
let pendingPortalLogin = false;

formLogin.addEventListener("submit", async (e) => {
  e.preventDefault();
  loginError.textContent = "";

  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();

    if (!res.ok) {
      loginError.textContent = data.error || "No fue posible iniciar sesión";
      return;
    }

    if (data.requiere_2fa) {
      pendingPortalLogin = data.portal === true;
      formLogin.classList.add("is-hidden");
      form2fa.classList.remove("is-hidden");
      document.getElementById("token-2fa").focus();
    } else {
      window.location.href = data.redirect || "/";
    }
  } catch (err) {
    loginError.textContent = "Error de conexión con el servidor";
  }
});

form2fa.addEventListener("submit", async (e) => {
  e.preventDefault();
  tokenError.textContent = "";

  const token = document.getElementById("token-2fa").value.trim();

  try {
    const res = await fetch("/api/auth/verificar-2fa", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(pendingPortalLogin ? { "X-Patient-Portal": "1" } : {}),
      },
      credentials: "same-origin",
      body: JSON.stringify({ token }),
    });
    const data = await res.json();

    if (!res.ok) {
      tokenError.textContent = data.error || "Código incorrecto";
      return;
    }
    window.location.href = data.redirect || "/";
  } catch (err) {
    tokenError.textContent = "Error de conexión con el servidor";
  }
});

document.getElementById("link-registro").addEventListener("click", async (e) => {
  e.preventDefault();
  const nombre = prompt("Nombre completo:");
  if (!nombre) return;
  const email = prompt("Correo electrónico:");
  if (!email) return;
  const password = prompt("Contraseña (mínimo 8 caracteres):");
  if (!password) return;

  const res = await fetch("/api/auth/registro", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nombre, email, password, rol: "paciente" }),
  });
  const data = await res.json();

  if (!res.ok) {
    alert(data.error || "No fue posible completar el registro");
    return;
  }
  alert("Cuenta creada. Ahora puedes iniciar sesión.");
});