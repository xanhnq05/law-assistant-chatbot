import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";

const baseURL = import.meta.env.VITE_API_URL || "http://localhost:8080";

/**
 * Axios instance chính.
 * - withCredentials: true để browser tự gửi cookie (refreshToken) theo mỗi request.
 * - Interceptor sẽ tự gọi /refresh khi accessToken hết hạn (401/403) và replay request cũ.
 */
export const axiosInstance = axios.create({
  baseURL,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

// ===== Type mở rộng để đánh dấu request đang retry =====
interface RetryAxiosRequestConfig extends InternalAxiosRequestConfig {
  _retry?: boolean;
  _isRefreshCall?: boolean;
}

// ===== Bộ đếm request đang chờ refresh =====
// Khi nhiều request cùng lúc bị 401, chỉ refresh 1 lần, các request còn lại chờ kết quả.
let isRefreshing = false;
let failedQueue: Array<{
  resolve: (value: unknown) => void;
  reject: (reason?: unknown) => void;
}> = [];

const processQueue = (error: unknown, token: string | null = null) => {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) {
      reject(error);
    } else {
      resolve(token);
    }
  });
  failedQueue = [];
};

// ===== Request interceptor: gắn accessToken nếu có =====
axiosInstance.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const accessToken = localStorage.getItem("accessToken");
    if (accessToken && config.headers) {
      config.headers.Authorization = `Bearer ${accessToken}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// ===== Response interceptor: tự refresh khi 401/403 =====
axiosInstance.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as RetryAxiosRequestConfig;

    // Không refresh cho chính endpoint /refresh để tránh vòng lặp vô tận
    if (originalRequest?._isRefreshCall) {
      return Promise.reject(error);
    }

    // Nếu là 401/403 và chưa retry -> gọi /refresh
    if (
      originalRequest &&
      (error.response?.status === 401 || error.response?.status === 403) &&
      !originalRequest._retry
    ) {
      if (isRefreshing) {
        // Đang có request khác refresh rồi -> xếp hàng chờ
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then(() => axiosInstance(originalRequest));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        // Gọi endpoint refresh (cookie refreshToken tự được gửi theo)
        const refreshResponse = await axios.post(
          `${baseURL}/refresh`,
          {},
          {
            withCredentials: true,
          }
        );

        const newAccessToken: string | undefined =
          refreshResponse.data?.accessToken ||
          refreshResponse.data?.access_token ||
          refreshResponse.data?.token;

        if (!newAccessToken) {
          throw new Error("Không nhận được accessToken mới từ /refresh");
        }

        // Lưu lại token mới
        localStorage.setItem("accessToken", newAccessToken);

        // Cập nhật header cho request gốc
        if (originalRequest.headers) {
          originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;
        }

        processQueue(null, newAccessToken);
        return axiosInstance(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        // Refresh thất bại -> xóa token + user, để guest dùng app tiếp
        localStorage.removeItem("accessToken");
        localStorage.removeItem("user");
        if (
          window.location.pathname !== "/" &&
          window.location.pathname !== "/sign-in" &&
          window.location.pathname !== "/sign-up"
        ) {
          window.location.href = "/";
        }
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);