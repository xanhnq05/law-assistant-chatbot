/* ============================================================
   Runtime configuration for the frontend.

   File này được serve cùng index.html và override giá trị mặc
   định trong script.js.

   Docker (port frontend container):    http://localhost:8080
   Local không Docker (python -m http.server): đổi thành cổng
                                            bạn đang serve (vd 5500)
                                            và trỏ thẳng về port
                                            backend mong muốn.
   ============================================================ */
window.__APP_CONFIG__ = window.__APP_CONFIG__ || {
  // Browser sẽ gọi các endpoint /auth/*, /chats/*, /api/* qua nginx proxy.
  API_BASE_URL: "http://localhost:8080"
};
