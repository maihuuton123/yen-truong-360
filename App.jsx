import { useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";

const PRODUCTION_API_BASE_URL = "https://yen-truong-360.onrender.com";
const isLocalFrontend =
  typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname);
const RAW_API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_API_URL ?? (isLocalFrontend ? "" : PRODUCTION_API_BASE_URL);
const API_BASE_URL = RAW_API_BASE_URL.replace(/\/$/, "");
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_REPORT_IMAGES = 5;
const ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp", "image/gif"];
const TRACKING_CODE_PATTERN = /^YT360-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{6}$/;
const AUTH_STORAGE_KEY = "yt360_admin_auth";

const navItems = [
  { path: "/", label: "Trang chủ" },
  { path: "/phan-anh", label: "Gửi phản ánh" },
  { path: "/tra-cuu", label: "Tra cứu" },
];

const guideSteps = [
  ["1", "Chọn nhóm phản ánh và khu vực gần đúng."],
  ["2", "Mô tả ngắn gọn, rõ sự việc cần hỗ trợ xử lý."],
  ["3", "Gửi phản ánh và lưu lại mã tra cứu được cấp."],
];

const lookupTimeline = [
  {
    key: "received",
    label: "ĐÃ TIẾP NHẬN",
    statuses: ["NEW", "RECEIVED"],
  },
  {
    key: "coordinating",
    label: "ĐANG PHỐI HỢP",
    statuses: ["COORDINATING"],
  },
  {
    key: "resolved",
    label: "ĐÃ XỬ LÝ",
    statuses: ["RESOLVED"],
  },
];

const adminNavItems = [
  { path: "/admin/dashboard", label: "Tổng quan" },
  { path: "/admin/reports", label: "Phản ánh" },
  { path: "/admin/statistics", label: "Thống kê" },
  { path: "/admin/categories", label: "Danh mục", adminOnly: true },
  { path: "/admin/users", label: "Tài khoản", adminOnly: true },
  { path: "/admin/audit-logs", label: "Nhật ký", adminOnly: true },
];

const statusOptions = [
  { value: "NEW", label: "Mới" },
  { value: "RECEIVED", label: "Đã tiếp nhận" },
  { value: "COORDINATING", label: "Đang phối hợp" },
  { value: "RESOLVED", label: "Đã xử lý" },
  { value: "OUT_OF_SCOPE", label: "Ngoài phạm vi" },
];

const statusLabels = Object.fromEntries(statusOptions.map((item) => [item.value, item.label]));
const DISPLAY_DATE_PATTERN = /^\d{2}\/\d{2}\/\d{4}$/;

function apiUrl(path) {
  return `${API_BASE_URL}${path}`;
}

function formatDisplayDateInput(value) {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [year, month, day] = value.split("-");
    return `${day}/${month}/${year}`;
  }

  const digits = value.replace(/\D/g, "").slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}

function displayDateToApiDate(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed) return "";
  if (trimmed.length < 10) return "";
  if (!DISPLAY_DATE_PATTERN.test(trimmed)) {
    throw new Error("Ngày lọc phải nhập theo dạng dd/mm/yyyy.");
  }

  const [dayText, monthText, yearText] = trimmed.split("/");
  const day = Number(dayText);
  const month = Number(monthText);
  const year = Number(yearText);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    throw new Error("Ngày lọc không hợp lệ.");
  }

  return `${yearText}-${monthText}-${dayText}`;
}

function buildAdminFilterParams(filters) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    let normalizedValue = value;
    if (key === "from_date" || key === "to_date") {
      normalizedValue = displayDateToApiDate(value);
    }
    if (normalizedValue !== undefined && normalizedValue !== null && String(normalizedValue).trim() !== "") {
      params.set(key, String(normalizedValue).trim());
    }
  });
  return params;
}

function AdminDateInput({ value, onChange }) {
  return (
    <input
      type="text"
      inputMode="numeric"
      maxLength="10"
      placeholder="dd/mm/yyyy"
      title="Nhập ngày theo dạng dd/mm/yyyy"
      value={value}
      onChange={(event) => onChange(formatDisplayDateInput(event.target.value))}
    />
  );
}

async function parseJsonResponse(response, fallbackMessage) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.toLowerCase().includes("application/json")) {
    const text = await response.text().catch(() => "");
    const preview = text.trim().slice(0, 80).toLowerCase();
    if (preview.startsWith("<!doctype") || preview.startsWith("<html")) {
      throw new Error("API đang trả về trang HTML thay vì dữ liệu JSON. Vui lòng kiểm tra backend/proxy API.");
    }
    throw new Error(fallbackMessage);
  }

  return response.json();
}

async function fetchJson(path) {
  const response = await fetch(apiUrl(path));
  const body = await parseJsonResponse(response, "Không tải được dữ liệu. Vui lòng thử lại.");
  if (!response.ok) {
    throw new Error(body?.detail || "Không tải được dữ liệu. Vui lòng thử lại.");
  }
  return body;
}

async function fetchLookupReport(trackingCode) {
  const response = await fetch(apiUrl(`/api/public/reports/${encodeURIComponent(trackingCode)}`));
  const body = await parseJsonResponse(response, "Chưa kết nối được hệ thống tra cứu. Vui lòng thử lại sau.");

  if (!response.ok) {
    throw new Error(
      body?.detail || "Không tìm thấy phản ánh với mã tra cứu này. Vui lòng kiểm tra lại mã.",
    );
  }

  return body;
}

async function loginAdmin(username, password) {
  const response = await fetch(apiUrl("/api/auth/login"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ username, password }),
  });
  const body = await parseJsonResponse(response, "Không đăng nhập được. Vui lòng thử lại.");

  if (!response.ok) {
    throw new Error(body?.detail || "Tên đăng nhập hoặc mật khẩu không đúng.");
  }

  return body;
}

async function fetchWithAuth(path, token, options = {}) {
  const response = await fetch(apiUrl(path), {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${token}`,
    },
  });

  if (response.status === 204) return null;

  const body = await parseJsonResponse(response, "Phiên đăng nhập không hợp lệ. Vui lòng đăng nhập lại.");
  if (!response.ok) {
    throw new Error(body?.detail || "Phiên đăng nhập không hợp lệ. Vui lòng đăng nhập lại.");
  }
  return body;
}

async function fetchAdminDashboard(token) {
  return fetchWithAuth("/api/admin/dashboard", token);
}

async function fetchAdminQr(token) {
  return fetchWithAuth("/api/admin/qr", token);
}

function isAdminDashboardPayload(body) {
  return (
    body &&
    Array.isArray(body.cards) &&
    body.work &&
    Number.isFinite(Number(body.work.new_reports)) &&
    Number.isFinite(Number(body.work.coordinating_reports)) &&
    Number.isFinite(Number(body.work.needs_update))
  );
}

async function fetchAdminReports(token, filters) {
  const params = buildAdminFilterParams(filters);
  return fetchWithAuth(`/api/admin/reports?${params.toString()}`, token);
}

async function fetchAdminStatistics(token, filters) {
  const params = buildAdminFilterParams(filters);
  return fetchWithAuth(`/api/admin/statistics?${params.toString()}`, token);
}

async function exportAdminStatisticsExcel(token, filters) {
  const params = buildAdminFilterParams(filters);
  const response = await fetch(apiUrl(`/api/admin/statistics/export?${params.toString()}`), {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    if (contentType.toLowerCase().includes("application/json")) {
      const body = await response.json();
      throw new Error(body?.detail || "Không xuất được Excel.");
    }
    throw new Error("Không xuất được Excel.");
  }
  if (!contentType.includes("spreadsheetml.sheet")) {
    throw new Error("API xuất Excel trả về định dạng không hợp lệ.");
  }

  const disposition = response.headers.get("content-disposition") || "";
  const filenameMatch = disposition.match(/filename\*=UTF-8''([^;]+)/) || disposition.match(/filename=([^;]+)/);
  const filename = filenameMatch ? decodeURIComponent(filenameMatch[1].replace(/"/g, "")) : "";
  return { blob: await response.blob(), filename };
}

async function downloadAdminQr(token) {
  const response = await fetch(apiUrl("/api/admin/qr/download"), {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });
  if (!response.ok) {
    throw new Error("Không tải được QR.");
  }
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.toLowerCase().includes("image/svg+xml")) {
    throw new Error("API QR trả về định dạng không hợp lệ.");
  }
  return response.blob();
}

async function fetchAdminCategories(token) {
  return fetchWithAuth("/api/admin/categories", token);
}

async function saveAdminCategory(token, category) {
  const isEdit = Boolean(category.id);
  return fetchWithAuth(isEdit ? `/api/admin/categories/${encodeURIComponent(category.id)}` : "/api/admin/categories", token, {
    method: isEdit ? "PUT" : "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      name: category.name,
      icon: category.icon || null,
      is_active: category.is_active,
      display_order: Number(category.display_order || 0),
    }),
  });
}

async function fetchAdminAreas(token) {
  return fetchWithAuth("/api/admin/areas", token);
}

async function saveAdminArea(token, area) {
  const isEdit = Boolean(area.id);
  return fetchWithAuth(isEdit ? `/api/admin/areas/${encodeURIComponent(area.id)}` : "/api/admin/areas", token, {
    method: isEdit ? "PUT" : "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      name: area.name,
      is_active: area.is_active,
      display_order: Number(area.display_order || 0),
    }),
  });
}

async function fetchAdminUsers(token) {
  return fetchWithAuth("/api/admin/users", token);
}

async function fetchAdminAuditLogs(token, filters) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      params.set(key, String(value).trim());
    }
  });
  return fetchWithAuth(`/api/admin/audit-logs?${params.toString()}`, token);
}

async function createAdminUser(token, user) {
  return fetchWithAuth("/api/admin/users", token, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      username: user.username,
      password: user.password,
      full_name: user.full_name,
      role: user.role,
      is_active: user.is_active,
    }),
  });
}

async function updateAdminUser(token, user) {
  return fetchWithAuth(`/api/admin/users/${encodeURIComponent(user.id)}`, token, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      full_name: user.full_name,
      role: user.role,
      is_active: user.is_active,
    }),
  });
}

async function resetAdminUserPassword(token, userId, password) {
  return fetchWithAuth(`/api/admin/users/${encodeURIComponent(userId)}/password`, token, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ password }),
  });
}

async function fetchAdminReportDetail(token, reportId) {
  return fetchWithAuth(`/api/admin/reports/${encodeURIComponent(reportId)}`, token);
}

async function fetchAdminReportTechnical(token, reportId) {
  return fetchWithAuth(`/api/admin/reports/${encodeURIComponent(reportId)}/technical`, token);
}

async function blockAdminReportSource(token, reportId, sourceType, reason) {
  return fetchWithAuth(`/api/admin/reports/${encodeURIComponent(reportId)}/source-blocks`, token, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ source_type: sourceType, reason }),
  });
}

async function unblockAdminReportSource(token, blockId) {
  return fetchWithAuth(`/api/admin/source-blocks/${encodeURIComponent(blockId)}/unblock`, token, {
    method: "POST",
  });
}

async function linkAdminRelatedReport(token, reportId, relatedReportId, reason) {
  return fetchWithAuth(`/api/admin/reports/${encodeURIComponent(reportId)}/related-reports`, token, {
    method: "POST",
    body: JSON.stringify({
      related_report_id: Number(relatedReportId),
      reason,
    }),
  });
}

async function transitionAdminReport(token, reportId, action, payload) {
  return fetchWithAuth(`/api/admin/reports/${encodeURIComponent(reportId)}/${action}`, token, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

async function fetchAdminAttachmentBlob(token, reportId, attachmentId) {
  const response = await fetch(
    apiUrl(`/api/admin/reports/${encodeURIComponent(reportId)}/attachments/${encodeURIComponent(attachmentId)}`),
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    },
  );

  if (!response.ok) {
    throw new Error("Không tải được ảnh đính kèm.");
  }

  return response.blob();
}

async function uploadAdminProcessingImages(token, reportId, attachmentType, files) {
  const payload = new FormData();
  payload.append("attachment_type", attachmentType);
  files.forEach((file) => payload.append("images", file));
  return fetchWithAuth(`/api/admin/reports/${encodeURIComponent(reportId)}/attachments`, token, {
    method: "POST",
    body: payload,
  });
}

function loadStoredAuth() {
  try {
    const raw = sessionStorage.getItem(AUTH_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    sessionStorage.removeItem(AUTH_STORAGE_KEY);
    return null;
  }
}

function storeAuth(auth) {
  if (!auth) {
    sessionStorage.removeItem(AUTH_STORAGE_KEY);
    return;
  }
  sessionStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth));
}

function formatDateTime(value) {
  if (!value) return "Chưa có";
  const rawValue = String(value);
  const normalizedValue = /\dT\d/.test(rawValue) && !/(Z|[+-]\d{2}:?\d{2})$/.test(rawValue)
    ? `${rawValue}Z`
    : rawValue;
  const date = new Date(normalizedValue);

  if (Number.isNaN(date.getTime())) return "Chưa có";

  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("vi-VN", {
      timeZone: "Asia/Ho_Chi_Minh",
      hour: "2-digit",
      minute: "2-digit",
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour12: false,
    }).formatToParts(date).map((part) => [part.type, part.value]),
  );

  return `${parts.hour}:${parts.minute} - ${parts.day}/${parts.month}/${parts.year}`;
}

function formatTechnicalValue(value) {
  if (value === null || value === undefined || String(value).trim() === "") return "Không ghi nhận";
  return String(value);
}

function formatTechnicalTime(value) {
  if (!value) return "Không ghi nhận";
  const formatted = formatDateTime(value);
  return formatted === "Chưa có" ? "Không ghi nhận" : formatted;
}

function canReceiveReport(role, status) {
  return ["ADMIN", "RECEIVER"].includes(role) && status === "NEW";
}

function canCoordinateReport(role, status) {
  return ["ADMIN", "RECEIVER"].includes(role) && status === "RECEIVED";
}

function canResolveReport(role, status) {
  return ["ADMIN", "HANDLER"].includes(role) && status === "COORDINATING";
}

function canMarkOutOfScope(role, status) {
  return ["ADMIN", "RECEIVER"].includes(role) && ["NEW", "RECEIVED", "COORDINATING"].includes(status);
}

function Header() {
  return (
    <header className="site-header">
      <NavLink to="/" className="brand" aria-label="Yên Trường 360">
        <span className="brand-mark">YT</span>
        <span>
          <strong>Yên Trường 360</strong>
          <small>Kênh phản ánh dân sinh</small>
        </span>
      </NavLink>

      <nav className="nav-links" aria-label="Điều hướng chính">
        {navItems.map((item) => (
          <NavLink key={item.path} to={item.path}>
            {item.label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}

function HomePage() {
  return (
    <main>
      <section className="home-hero">
        <div className="home-copy">
          <p className="eyebrow">Yên Trường 360</p>
          <h1>YÊN TRƯỜNG 360</h1>
          <p className="subtitle">Kênh hỗ trợ phản ánh dân sinh</p>
          <p className="message">Quét nhanh – Phản ánh dễ – Theo dõi rõ – Phối hợp hiệu quả</p>

          <div className="home-actions" aria-label="Hành động chính">
            <Link className="primary-action xl" to="/phan-anh">
              Gửi phản ánh
            </Link>
            <Link className="secondary-action xl" to="/tra-cuu">
              Tra cứu kết quả
            </Link>
          </div>
        </div>

        <div className="home-panel" aria-label="Minh họa mã tra cứu">
          <div className="code-ticket">
            <span>Mã tra cứu mẫu</span>
            <strong>YT360-7K9M2Q</strong>
          </div>
          <div className="status-track">
            <span className="active">Đã tiếp nhận</span>
            <span>Đang phối hợp</span>
            <span>Đã xử lý</span>
          </div>
        </div>
      </section>

      <section className="guide-section" aria-label="Hướng dẫn ngắn">
        <div className="section-heading">
          <p className="eyebrow">Hướng dẫn</p>
          <h2>Gửi phản ánh trong vài bước đơn giản</h2>
        </div>
        <div className="guide-grid">
          {guideSteps.map(([number, text]) => (
            <article className="guide-card" key={number}>
              <span>{number}</span>
              <p>{text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="warning-box" role="note">
        <strong>Lưu ý quan trọng</strong>
        <p>
          Hệ thống không thay thế các kênh khẩn cấp, tố giác/tin báo về tội phạm
          hoặc kênh chuyên ngành theo quy định.
        </p>
      </section>
    </main>
  );
}

function CitizenReportPage() {
  const imageInputRef = useRef(null);
  const submitLockRef = useRef(false);
  const [categories, setCategories] = useState([]);
  const [areas, setAreas] = useState([]);
  const [isLoadingOptions, setIsLoadingOptions] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [success, setSuccess] = useState(null);
  const [copied, setCopied] = useState(false);
  const [form, setForm] = useState({
    categoryId: "",
    areaId: "",
    description: "",
    images: [],
    confirmed: false,
  });
  const [errors, setErrors] = useState({});

  const imagePreviews = useMemo(() => form.images.map((file) => URL.createObjectURL(file)), [form.images]);

  useEffect(() => {
    return () => {
      imagePreviews.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [imagePreviews]);

  useEffect(() => {
    let isMounted = true;

    async function loadOptions() {
      try {
        const [categoryData, areaData] = await Promise.all([
          fetchJson("/api/public/categories"),
          fetchJson("/api/public/areas"),
        ]);
        if (!isMounted) return;
        setCategories(categoryData);
        setAreas(areaData);
      } catch (error) {
        if (!isMounted) return;
        setLoadError(error.message || "Không tải được dữ liệu.");
      } finally {
        if (isMounted) setIsLoadingOptions(false);
      }
    }

    loadOptions();
    return () => {
      isMounted = false;
    };
  }, []);

  function updateField(name, value) {
    setForm((current) => ({ ...current, [name]: value }));
    setErrors((current) => ({ ...current, [name]: "" }));
    setSubmitError("");
  }

  function handleImageChange(event) {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0) {
      updateField("images", []);
      return;
    }

    if (files.length > MAX_REPORT_IMAGES) {
      setErrors((current) => ({ ...current, images: `Chỉ được chọn tối đa ${MAX_REPORT_IMAGES} ảnh.` }));
      event.target.value = "";
      return;
    }

    const invalidType = files.find((file) => !ALLOWED_IMAGE_TYPES.includes(file.type));
    if (invalidType) {
      setErrors((current) => ({ ...current, images: "Chỉ chấp nhận ảnh JPG, PNG, WEBP hoặc GIF." }));
      event.target.value = "";
      return;
    }

    const oversized = files.find((file) => file.size > MAX_IMAGE_BYTES);
    if (oversized) {
      setErrors((current) => ({ ...current, images: "Mỗi ảnh không được vượt quá 5 MB." }));
      event.target.value = "";
      return;
    }

    updateField("images", files);
  }

  function removeImage(indexToRemove) {
    updateField(
      "images",
      form.images.filter((_, index) => index !== indexToRemove),
    );
    if (imageInputRef.current) {
      imageInputRef.current.value = "";
    }
  }

  function validateForm() {
    const nextErrors = {};
    if (!form.categoryId) nextErrors.categoryId = "Vui lòng chọn nhóm phản ánh.";
    if (!form.areaId) nextErrors.areaId = "Vui lòng chọn khu vực.";
    if (!form.description.trim()) nextErrors.description = "Vui lòng nhập mô tả phản ánh.";
    if (form.description.trim().length > 2000) {
      nextErrors.description = "Mô tả không được vượt quá 2000 ký tự.";
    }
    if (!form.confirmed) nextErrors.confirmed = "Vui lòng xác nhận nội dung trước khi gửi.";

    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (submitLockRef.current) return;
    if (!validateForm()) return;

    submitLockRef.current = true;
    setIsSubmitting(true);
    setSubmitError("");

    const payload = new FormData();
    payload.append("category_id", form.categoryId);
    payload.append("area_id", form.areaId);
    payload.append("description", form.description.trim());
    form.images.forEach((file) => payload.append("images", file));

    try {
      const response = await fetch(apiUrl("/api/public/reports"), {
        method: "POST",
        body: payload,
      });
      const body = await parseJsonResponse(response, "Không gửi được phản ánh. Vui lòng thử lại.");

      if (!response.ok) {
        throw new Error(body.detail || "Không gửi được phản ánh. Vui lòng thử lại.");
      }

      setSuccess(body);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (error) {
      setSubmitError(error.message || "Không gửi được phản ánh. Vui lòng thử lại.");
    } finally {
      submitLockRef.current = false;
      setIsSubmitting(false);
    }
  }

  async function copyTrackingCode() {
    if (!success?.tracking_code) return;

    try {
      await navigator.clipboard.writeText(success.tracking_code);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  if (success) {
    return (
      <main className="success-page">
        <section className="success-card" aria-live="polite">
          <p className="eyebrow">Phản ánh đã được tiếp nhận</p>
          <h1>PHẢN ÁNH ĐÃ ĐƯỢC TIẾP NHẬN</h1>
          <div className="tracking-card">
            <span>Mã tra cứu</span>
            <strong>{success.tracking_code}</strong>
          </div>
          <p className="success-note">
            Vui lòng lưu lại mã này để tra cứu tình trạng xử lý phản ánh.
          </p>
          <div className="success-actions">
            <button className="primary-action" type="button" onClick={copyTrackingCode}>
              {copied ? "Đã sao chép mã" : "Sao chép mã"}
            </button>
            <Link className="secondary-action" to="/tra-cuu">
              Tra cứu ngay
            </Link>
            <Link className="text-action" to="/">
              Về trang chủ
            </Link>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="report-page">
      <section className="report-heading">
        <p className="eyebrow">Gửi phản ánh</p>
        <h1>Phản ánh dân sinh</h1>
        <p>
          Không cần đăng nhập, không yêu cầu CCCD, GPS hoặc số điện thoại. Vui lòng mô tả rõ
          nội dung để cán bộ tiếp nhận thuận lợi hơn.
        </p>
      </section>

      <section className="warning-box compact" role="note">
        <strong>Lưu ý</strong>
        <p>
          Hệ thống không thay thế các kênh khẩn cấp, tố giác/tin báo về tội phạm
          hoặc kênh chuyên ngành theo quy định.
        </p>
      </section>

      <form className="citizen-form" onSubmit={handleSubmit} noValidate>
        {isLoadingOptions && <div className="form-status">Đang tải danh mục...</div>}
        {loadError && <div className="form-error">{loadError}</div>}

        <label>
          <span>1. Nhóm phản ánh</span>
          <select
            value={form.categoryId}
            onChange={(event) => updateField("categoryId", event.target.value)}
            disabled={isLoadingOptions || Boolean(loadError)}
          >
            <option value="">Chọn nhóm phản ánh</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
          {errors.categoryId && <small className="field-error">{errors.categoryId}</small>}
        </label>

        <label>
          <span>2. Khu vực</span>
          <select
            value={form.areaId}
            onChange={(event) => updateField("areaId", event.target.value)}
            disabled={isLoadingOptions || Boolean(loadError)}
          >
            <option value="">Chọn khu vực</option>
            {areas.map((area) => (
              <option key={area.id} value={area.id}>
                {area.name}
              </option>
            ))}
          </select>
          {errors.areaId && <small className="field-error">{errors.areaId}</small>}
        </label>

        <label>
          <span>3. Mô tả</span>
          <textarea
            value={form.description}
            maxLength={2000}
            placeholder="Ví dụ: Cây đổ chắn một phần đường, cần hỗ trợ xử lý..."
            onChange={(event) => updateField("description", event.target.value)}
          />
          <small className="helper-text">{form.description.trim().length}/2000 ký tự</small>
          {errors.description && <small className="field-error">{errors.description}</small>}
        </label>

        <div className="upload-field">
          <label htmlFor="report-image">
            <span>4. Hình ảnh tùy chọn</span>
            <input
              id="report-image"
              ref={imageInputRef}
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp,image/gif"
              onChange={handleImageChange}
            />
          </label>
          <p className="helper-text">
            Chấp nhận JPG, PNG, WEBP hoặc GIF. Tối đa {MAX_REPORT_IMAGES} ảnh, mỗi ảnh 5 MB.
          </p>
          {errors.images && <small className="field-error">{errors.images}</small>}
          {imagePreviews.length > 0 && (
            <div className="image-preview-grid">
              {imagePreviews.map((previewUrl, index) => (
                <div className="image-preview" key={`${form.images[index]?.name}-${index}`}>
                  <img src={previewUrl} alt={`Ảnh xem trước ${index + 1}`} />
                  <button type="button" onClick={() => removeImage(index)}>
                    Bỏ ảnh
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <label className="confirm-box">
          <input
            type="checkbox"
            checked={form.confirmed}
            onChange={(event) => updateField("confirmed", event.target.checked)}
          />
          <span>5. Xác nhận nội dung phản ánh là đúng với thông tin tôi cung cấp.</span>
        </label>
        {errors.confirmed && <small className="field-error">{errors.confirmed}</small>}

        {submitError && <div className="form-error">{submitError}</div>}

        <button className="submit-button" type="submit" disabled={isSubmitting || isLoadingOptions || Boolean(loadError)}>
          {isSubmitting ? "Đang gửi..." : "Gửi phản ánh"}
        </button>
      </form>
    </main>
  );
}

function LookupPage() {
  const [trackingCode, setTrackingCode] = useState("");
  const [lookupError, setLookupError] = useState("");
  const [lookupResult, setLookupResult] = useState(null);
  const [isLookingUp, setIsLookingUp] = useState(false);

  const completedStatuses = useMemo(() => {
    if (!lookupResult) return new Set();
    return new Set([
      lookupResult.public_status?.code,
      ...(lookupResult.public_status_history ?? []).map((item) => item.public_status?.code),
    ]);
  }, [lookupResult]);

  function updateTrackingCode(value) {
    setTrackingCode(value.toUpperCase().replace(/\s/g, ""));
    setLookupError("");
  }

  async function handleLookup(event) {
    event.preventDefault();
    const cleanedCode = trackingCode.trim().toUpperCase();
    if (!cleanedCode) {
      setLookupError("Vui lòng nhập mã tra cứu.");
      setLookupResult(null);
      return;
    }
    if (!TRACKING_CODE_PATTERN.test(cleanedCode)) {
      setLookupError("Mã tra cứu không hợp lệ. Vui lòng kiểm tra lại mã.");
      setLookupResult(null);
      return;
    }

    setIsLookingUp(true);
    setLookupError("");
    setLookupResult(null);

    try {
      const result = await fetchLookupReport(cleanedCode);
      setLookupResult(result);
    } catch (error) {
      setLookupError(error.message || "Không tìm thấy phản ánh với mã tra cứu này. Vui lòng kiểm tra lại mã.");
    } finally {
      setIsLookingUp(false);
    }
  }

  return (
    <main className="lookup-page">
      <section className="lookup-card">
        <div className="lookup-heading">
          <p className="eyebrow">Tra cứu kết quả</p>
          <h1>Tra cứu phản ánh</h1>
          <p>Nhập mã tra cứu đã được cấp sau khi gửi phản ánh.</p>
        </div>

        <form className="lookup-form" onSubmit={handleLookup} noValidate>
          <label>
            <span>Mã tra cứu</span>
            <input
              type="text"
              inputMode="text"
              autoComplete="off"
              placeholder="Ví dụ: YT360-7K9M2Q"
              value={trackingCode}
              onChange={(event) => updateTrackingCode(event.target.value)}
            />
          </label>
          {lookupError && <div className="form-error">{lookupError}</div>}
          <button className="submit-button" type="submit" disabled={isLookingUp}>
            {isLookingUp ? "Đang tra cứu..." : "Tra cứu"}
          </button>
        </form>

        {lookupResult && (
          <section className="lookup-result" aria-live="polite">
            <div className="result-title">
              <span>Mã phản ánh</span>
              <strong>{lookupResult.tracking_code}</strong>
            </div>

            <dl className="report-summary">
              <div>
                <dt>Nhóm</dt>
                <dd>{lookupResult.category}</dd>
              </div>
              <div>
                <dt>Khu vực</dt>
                <dd>{lookupResult.area || "Chưa xác định"}</dd>
              </div>
              <div>
                <dt>Ngày gửi</dt>
                <dd>{formatDateTime(lookupResult.created_at)}</dd>
              </div>
              <div>
                <dt>Cập nhật gần nhất</dt>
                <dd>{formatDateTime(lookupResult.updated_at)}</dd>
              </div>
            </dl>

            <div className="current-status">
              <span>Trạng thái hiện tại</span>
              <strong>{lookupResult.public_status?.label}</strong>
            </div>

            <ol className="status-timeline" aria-label="Tiến trình xử lý phản ánh">
              {lookupTimeline.map((step) => {
                const isDone = step.statuses.some((statusCode) => completedStatuses.has(statusCode));
                return (
                  <li className={isDone ? "done" : ""} key={step.key}>
                    <span aria-hidden="true">{isDone ? "✓" : ""}</span>
                    <strong>{step.label}</strong>
                  </li>
                );
              })}
            </ol>

            {lookupResult.public_response && (
              <div className="public-response">
                <span>Kết quả</span>
                <p>{lookupResult.public_response}</p>
              </div>
            )}

            {lookupResult.public_status_history?.length > 0 && (
              <div className="public-history">
                <span>Lịch sử công khai</span>
                <ul>
                  {lookupResult.public_status_history.map((item) => (
                    <li key={`${item.public_status.code}-${item.created_at}`}>
                      <strong>{item.public_status.label}</strong>
                      <time>{formatDateTime(item.created_at)}</time>
                      {item.public_note && <p>{item.public_note}</p>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}
      </section>
    </main>
  );
}
function ProtectedAdminRoute({ auth, children }) {
  if (!auth?.accessToken) {
    return <Navigate to="/admin/login" replace />;
  }
  return children;
}

function AdminLoginPage({ auth, onLogin }) {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (auth?.accessToken) {
    return <Navigate to="/admin/dashboard" replace />;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const cleanedUsername = username.trim();
    if (!cleanedUsername || !password) {
      setError("Vui lòng nhập tên đăng nhập và mật khẩu.");
      return;
    }

    setIsSubmitting(true);
    setError("");

    try {
      const result = await loginAdmin(cleanedUsername, password);
      onLogin(result);
      navigate("/admin/dashboard", { replace: true });
    } catch (loginError) {
      setError(loginError.message || "Tên đăng nhập hoặc mật khẩu không đúng.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="admin-page">
      <section className="admin-card">
        <p className="eyebrow">Quản trị</p>
        <h1>Đăng nhập quản trị</h1>
        <form className="admin-login-form" onSubmit={handleSubmit} noValidate>
          <label>
            <span>Tên đăng nhập</span>
            <input
              type="text"
              autoComplete="username"
              value={username}
              onChange={(event) => {
                setUsername(event.target.value);
                setError("");
              }}
            />
          </label>
          <label>
            <span>Mật khẩu</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                setError("");
              }}
            />
          </label>
          {error && <div className="form-error">{error}</div>}
          <button className="submit-button" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Đang đăng nhập..." : "Đăng nhập"}
          </button>
        </form>
      </section>
    </main>
  );
}

function AdminLayout({ auth, onLogout, children }) {
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  async function handleLogout() {
    setIsLoggingOut(true);
    try {
      await fetchWithAuth("/api/auth/logout", auth.accessToken, { method: "POST" });
    } catch {
      // The local session is still cleared even when the server token has already expired.
    } finally {
      onLogout();
      setIsLoggingOut(false);
    }
  }

  return (
    <main className="admin-shell">
      <aside className="admin-sidebar" aria-label="Điều hướng quản trị">
        <div className="admin-user">
          <span>{auth.user?.role || "ADMIN"}</span>
          <strong>{auth.user?.fullName || auth.user?.full_name || auth.user?.username}</strong>
        </div>
        <nav>
          {adminNavItems.map((item) => {
            const isUnavailable = item.disabled || (item.adminOnly && auth.user?.role !== "ADMIN");
            return isUnavailable ? (
              <span className="admin-nav-disabled" key={item.path}>
                {item.label}
              </span>
            ) : (
              <NavLink key={item.path} to={item.path}>
                {item.label}
              </NavLink>
            );
          })}
        </nav>
        <button className="admin-logout" type="button" onClick={handleLogout} disabled={isLoggingOut}>
          {isLoggingOut ? "Đang đăng xuất..." : "Đăng xuất"}
        </button>
      </aside>

      <section className="admin-content">{children}</section>
    </main>
  );
}

function DashboardPage({ auth }) {
  const [dashboard, setDashboard] = useState(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;

    async function loadDashboard() {
      try {
        const body = await fetchAdminDashboard(auth.accessToken);
        if (!isMounted) return;
        if (!isAdminDashboardPayload(body)) {
          throw new Error(
            "Backend quản trị trên Render chưa cập nhật bản mới. Vui lòng deploy latest commit để tải số liệu.",
          );
        }
        setDashboard(body);
      } catch (loadError) {
        if (!isMounted) return;
        setError(loadError.message || "Phiên đăng nhập không hợp lệ. Vui lòng đăng nhập lại.");
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }

    loadDashboard();
    return () => {
      isMounted = false;
    };
  }, [auth.accessToken]);

  return (
    <>
      <section className="admin-section-heading">
        <p className="eyebrow">Tổng quan</p>
        <h1>Tổng quan xử lý</h1>
        <p>Theo dõi nhanh khối lượng phản ánh và việc cần xử lý.</p>
      </section>

      {isLoading && <div className="form-status">Đang tải số liệu quản trị...</div>}
      {error && <div className="form-error">{error}</div>}

      {dashboard && (
        <>
          <section className="admin-metric-grid" aria-label="Số liệu tổng quan">
            {dashboard.cards.map((card) => (
              <article className={`admin-metric-card ${card.key}`} key={card.key}>
                <span>{card.label}</span>
                <strong>{card.value}</strong>
              </article>
            ))}
          </section>

          <section className="admin-card work-card">
            <div className="admin-card-title">
              <p className="eyebrow">Việc cần xem</p>
              <h2>VIỆC CẦN XEM</h2>
            </div>
            <ul className="work-list">
              <li>
                <strong>{String(dashboard.work.new_reports).padStart(2, "0")}</strong>
                <span>phản ánh mới</span>
              </li>
              <li>
                <strong>{String(dashboard.work.coordinating_reports).padStart(2, "0")}</strong>
                <span>đang phối hợp</span>
              </li>
              <li>
                <strong>{String(dashboard.work.needs_update).padStart(2, "0")}</strong>
                <span>cần cập nhật</span>
              </li>
            </ul>
          </section>

          {auth.user?.role === "ADMIN" && <AdminQrPanel auth={auth} />}
        </>
      )}
    </>
  );
}

function AdminQrPanel({ auth }) {
  const [qr, setQr] = useState(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isDownloading, setIsDownloading] = useState(false);

  useEffect(() => {
    let isMounted = true;

    async function loadQr() {
      try {
        const body = await fetchAdminQr(auth.accessToken);
        if (isMounted) setQr(body);
      } catch (loadError) {
        if (isMounted) setError(loadError.message || "Không tải được mã QR.");
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }

    loadQr();
    return () => {
      isMounted = false;
    };
  }, [auth.accessToken]);

  async function handleDownload() {
    if (isDownloading) return;
    setIsDownloading(true);
    setError("");
    try {
      const blob = await downloadAdminQr(auth.accessToken);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "YenTruong360_QR.svg";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (downloadError) {
      setError(downloadError.message || "Không tải được QR.");
    } finally {
      setIsDownloading(false);
    }
  }

  return (
    <section className="admin-card qr-card">
      <div className="admin-card-title">
        <p className="eyebrow">QR demo</p>
        <h2>Mã QR trang người dân</h2>
      </div>

      {isLoading && <div className="form-status">Đang tạo mã QR...</div>}
      {error && <div className="form-error">{error}</div>}

      {qr && (
        <div className="qr-content">
          <div className="qr-preview" aria-label="Mã QR Yên Trường 360" dangerouslySetInnerHTML={{ __html: qr.svg }} />
          <div className="qr-meta">
            <span>Đường dẫn</span>
            <strong>{qr.target_url}</strong>
            <button className="primary-action" type="button" onClick={handleDownload} disabled={isDownloading}>
              {isDownloading ? "Đang tải..." : "Tải QR"}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function AdminReportsPage({ auth }) {
  const [categories, setCategories] = useState([]);
  const [areas, setAreas] = useState([]);
  const [reports, setReports] = useState(null);
  const [filters, setFilters] = useState({
    tracking_code: "",
    status: "",
    category_id: "",
    area_id: "",
    from_date: "",
    to_date: "",
    page: 1,
    page_size: 10,
    sort_by: "created_at",
    sort_order: "desc",
  });
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;
    async function loadOptions() {
      try {
        const [categoryData, areaData] = await Promise.all([
          fetchJson("/api/public/categories"),
          fetchJson("/api/public/areas"),
        ]);
        if (!isMounted) return;
        setCategories(categoryData);
        setAreas(areaData);
      } catch (loadError) {
        if (isMounted) setError(loadError.message || "Không tải được danh mục lọc.");
      }
    }
    loadOptions();
    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    let isMounted = true;
    async function loadReports() {
      setIsLoading(true);
      setError("");
      try {
        const body = await fetchAdminReports(auth.accessToken, filters);
        if (!isMounted) return;
        setReports(body);
      } catch (loadError) {
        if (isMounted) setError(loadError.message || "Không tải được danh sách phản ánh.");
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }
    loadReports();
    return () => {
      isMounted = false;
    };
  }, [auth.accessToken, filters]);

  function updateFilter(name, value) {
    setFilters((current) => ({ ...current, [name]: value, page: 1 }));
  }

  function clearFilters() {
    setFilters({
      tracking_code: "",
      status: "",
      category_id: "",
      area_id: "",
      from_date: "",
      to_date: "",
      page: 1,
      page_size: 10,
      sort_by: "created_at",
      sort_order: "desc",
    });
  }

  function changePage(nextPage) {
    setFilters((current) => ({ ...current, page: nextPage }));
  }

  return (
    <>
      <section className="admin-section-heading">
        <p className="eyebrow">Phản ánh</p>
        <h1>Danh sách phản ánh</h1>
        <p>Lọc, sắp xếp và phân trang trực tiếp từ backend.</p>
      </section>

      <section className="admin-card report-filter-card">
        <label>
          <span>Mã tra cứu</span>
          <input
            type="text"
            placeholder="YT360-..."
            value={filters.tracking_code}
            onChange={(event) => updateFilter("tracking_code", event.target.value.toUpperCase())}
          />
        </label>
        <label>
          <span>Trạng thái</span>
          <select value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}>
            <option value="">Tất cả</option>
            {statusOptions.map((status) => (
              <option key={status.value} value={status.value}>
                {status.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Nhóm</span>
          <select value={filters.category_id} onChange={(event) => updateFilter("category_id", event.target.value)}>
            <option value="">Tất cả</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Khu vực</span>
          <select value={filters.area_id} onChange={(event) => updateFilter("area_id", event.target.value)}>
            <option value="">Tất cả</option>
            {areas.map((area) => (
              <option key={area.id} value={area.id}>
                {area.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Từ ngày</span>
          <AdminDateInput value={filters.from_date} onChange={(value) => updateFilter("from_date", value)} />
        </label>
        <label>
          <span>Đến ngày</span>
          <AdminDateInput value={filters.to_date} onChange={(value) => updateFilter("to_date", value)} />
        </label>
        <label>
          <span>Sắp xếp</span>
          <select value={filters.sort_by} onChange={(event) => updateFilter("sort_by", event.target.value)}>
            <option value="created_at">Thời gian gửi</option>
            <option value="updated_at">Cập nhật gần nhất</option>
            <option value="tracking_code">Mã phản ánh</option>
            <option value="status">Trạng thái</option>
          </select>
        </label>
        <label>
          <span>Thứ tự</span>
          <select value={filters.sort_order} onChange={(event) => updateFilter("sort_order", event.target.value)}>
            <option value="desc">Mới trước</option>
            <option value="asc">Cũ trước</option>
          </select>
        </label>
        <button className="secondary-action filter-reset" type="button" onClick={clearFilters}>
          Xóa lọc
        </button>
      </section>

      {error && <div className="form-error">{error}</div>}
      {isLoading && <div className="form-status">Đang tải danh sách phản ánh...</div>}

      {reports && (
        <section className="admin-card report-table-card">
          <div className="table-summary">
            <strong>{reports.total}</strong>
            <span>phản ánh phù hợp</span>
          </div>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Mã</th>
                  <th>Thời gian</th>
                  <th>Nhóm</th>
                  <th>Khu vực</th>
                  <th>Trạng thái</th>
                  <th>Thao tác</th>
                </tr>
              </thead>
              <tbody>
                {reports.items.length === 0 && (
                  <tr>
                    <td colSpan="6">Không có phản ánh phù hợp.</td>
                  </tr>
                )}
                {reports.items.map((report) => (
                  <tr key={report.tracking_code}>
                    <td>
                      <strong>{report.tracking_code}</strong>
                    </td>
                    <td>{formatDateTime(report.created_at)}</td>
                    <td>{report.category}</td>
                    <td>{report.area || "Chưa xác định"}</td>
                    <td>
                      <span className={`status-pill ${report.status.toLowerCase()}`}>
                        {statusLabels[report.status] || report.status}
                      </span>
                    </td>
                    <td>
                      <Link className="table-action" to={`/admin/reports/${report.id}`}>
                        Xem
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <button type="button" disabled={reports.page <= 1} onClick={() => changePage(reports.page - 1)}>
              Trước
            </button>
            <span>
              Trang {reports.page}/{reports.total_pages}
            </span>
            <button
              type="button"
              disabled={reports.page >= reports.total_pages}
              onClick={() => changePage(reports.page + 1)}
            >
              Sau
            </button>
          </div>
        </section>
      )}
    </>
  );
}

const statisticsStatusCards = [
  ["total_reports", "Tổng phản ánh", "total"],
  ["new_reports", "Phản ánh mới", "new"],
  ["received_reports", "Đã tiếp nhận", "received"],
  ["coordinating_reports", "Đang phối hợp", "coordinating"],
  ["resolved_reports", "Đã xử lý", "resolved"],
  ["out_of_scope_reports", "Không thuộc phạm vi", "out_of_scope"],
];

function AdminStatisticsPage({ auth }) {
  const [categories, setCategories] = useState([]);
  const [areas, setAreas] = useState([]);
  const [statistics, setStatistics] = useState(null);
  const [filters, setFilters] = useState({
    from_date: "",
    to_date: "",
    category_id: "",
    area_id: "",
    status: "",
  });
  const [error, setError] = useState("");
  const [exportError, setExportError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isExporting, setIsExporting] = useState(false);

  useEffect(() => {
    let isMounted = true;
    async function loadOptions() {
      try {
        const [categoryData, areaData] = await Promise.all([
          fetchJson("/api/public/categories"),
          fetchJson("/api/public/areas"),
        ]);
        if (!isMounted) return;
        setCategories(categoryData);
        setAreas(areaData);
      } catch (loadError) {
        if (isMounted) setError(loadError.message || "Không tải được danh mục lọc.");
      }
    }
    loadOptions();
    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    let isMounted = true;
    async function loadStatistics() {
      setIsLoading(true);
      setError("");
      try {
        const body = await fetchAdminStatistics(auth.accessToken, filters);
        if (!isMounted) return;
        setStatistics(body);
      } catch (loadError) {
        if (isMounted) setError(loadError.message || "Không tải được thống kê.");
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }
    loadStatistics();
    return () => {
      isMounted = false;
    };
  }, [auth.accessToken, filters]);

  function updateFilter(name, value) {
    setFilters((current) => ({ ...current, [name]: value }));
    setExportError("");
  }

  function clearFilters() {
    setFilters({
      from_date: "",
      to_date: "",
      category_id: "",
      area_id: "",
      status: "",
    });
    setExportError("");
  }

  async function handleExport() {
    if (isExporting) return;
    setIsExporting(true);
    setExportError("");
    try {
      const { blob, filename } = await exportAdminStatisticsExcel(auth.accessToken, filters);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename || "YenTruong360_ThongKe.xlsx";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (downloadError) {
      setExportError(downloadError.message || "Không xuất được Excel.");
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <>
      <section className="admin-section-heading">
        <p className="eyebrow">Thống kê</p>
        <h1>Thống kê phản ánh</h1>
        <p>Tổng hợp theo trạng thái, nhóm, khu vực và khoảng thời gian.</p>
      </section>

      <section className="admin-card report-filter-card statistics-filter-card">
        <label>
          <span>Từ ngày</span>
          <AdminDateInput value={filters.from_date} onChange={(value) => updateFilter("from_date", value)} />
        </label>
        <label>
          <span>Đến ngày</span>
          <AdminDateInput value={filters.to_date} onChange={(value) => updateFilter("to_date", value)} />
        </label>
        <label>
          <span>Nhóm</span>
          <select value={filters.category_id} onChange={(event) => updateFilter("category_id", event.target.value)}>
            <option value="">Tất cả</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Khu vực</span>
          <select value={filters.area_id} onChange={(event) => updateFilter("area_id", event.target.value)}>
            <option value="">Tất cả</option>
            {areas.map((area) => (
              <option key={area.id} value={area.id}>
                {area.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Trạng thái</span>
          <select value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}>
            <option value="">Tất cả</option>
            {statusOptions.map((status) => (
              <option key={status.value} value={status.value}>
                {status.label}
              </option>
            ))}
          </select>
        </label>
        <button className="secondary-action filter-reset" type="button" onClick={clearFilters}>
          Xóa lọc
        </button>
        <button className="primary-action statistics-export-button" type="button" onClick={handleExport} disabled={isExporting}>
          {isExporting ? "Đang xuất..." : "Xuất Excel"}
        </button>
      </section>

      {isLoading && <div className="form-status">Đang tải thống kê...</div>}
      {error && <div className="form-error">{error}</div>}
      {exportError && <div className="form-error">{exportError}</div>}

      {statistics && (
        <>
          <section className="admin-metric-grid statistics-metric-grid" aria-label="Số liệu thống kê">
            {statisticsStatusCards.map(([key, label, className]) => (
              <article className={`admin-metric-card ${className}`} key={key}>
                <span>{label}</span>
                <strong>{statistics[key]}</strong>
              </article>
            ))}
          </section>

          <section className="statistics-grid">
            <StatisticsBucketCard title="Theo nhóm phản ánh" items={statistics.by_category} />
            <StatisticsBucketCard title="Theo khu vực" items={statistics.by_area} />
            <StatisticsBucketCard title="Theo khoảng thời gian" items={statistics.by_date} />
          </section>
        </>
      )}
    </>
  );
}

function StatisticsBucketCard({ title, items }) {
  const maxValue = Math.max(1, ...items.map((item) => Number(item.value) || 0));

  return (
    <article className="admin-card statistics-bucket-card">
      <div className="admin-card-title">
        <p className="eyebrow">Thống kê</p>
        <h2>{title}</h2>
      </div>
      {items.length === 0 && <p className="admin-muted">Không có dữ liệu.</p>}
      {items.length > 0 && (
        <ul className="statistics-bars">
          {items.map((item) => {
            const width = `${Math.max(6, Math.round((Number(item.value) / maxValue) * 100))}%`;
            return (
              <li key={item.key}>
                <div>
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </div>
                <i style={{ width }} aria-hidden="true" />
              </li>
            );
          })}
        </ul>
      )}
    </article>
  );
}

const emptyCategoryForm = {
  id: "",
  name: "",
  icon: "",
  is_active: true,
  display_order: 0,
};

const emptyAreaForm = {
  id: "",
  name: "",
  is_active: true,
  display_order: 0,
};

function AdminCatalogsPage({ auth }) {
  const [categories, setCategories] = useState([]);
  const [areas, setAreas] = useState([]);
  const [categoryForm, setCategoryForm] = useState(emptyCategoryForm);
  const [areaForm, setAreaForm] = useState(emptyAreaForm);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [savingTarget, setSavingTarget] = useState("");

  async function loadCatalogs() {
    setIsLoading(true);
    setError("");
    try {
      const [categoryData, areaData] = await Promise.all([
        fetchAdminCategories(auth.accessToken),
        fetchAdminAreas(auth.accessToken),
      ]);
      setCategories(categoryData);
      setAreas(areaData);
    } catch (loadError) {
      setError(loadError.message || "Không tải được danh mục.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadCatalogs();
  }, [auth.accessToken]);

  function updateCategoryField(name, value) {
    setCategoryForm((current) => ({ ...current, [name]: value }));
    setError("");
    setMessage("");
  }

  function updateAreaField(name, value) {
    setAreaForm((current) => ({ ...current, [name]: value }));
    setError("");
    setMessage("");
  }

  function editCategory(category) {
    setCategoryForm({
      id: category.id,
      name: category.name,
      icon: category.icon || "",
      is_active: category.is_active,
      display_order: category.display_order,
    });
    setMessage("");
    setError("");
  }

  function editArea(area) {
    setAreaForm({
      id: area.id,
      name: area.name,
      is_active: area.is_active,
      display_order: area.display_order,
    });
    setMessage("");
    setError("");
  }

  async function submitCategory(event) {
    event.preventDefault();
    if (!categoryForm.name.trim()) {
      setError("Vui lòng nhập tên nhóm phản ánh.");
      return;
    }

    setSavingTarget("category-form");
    setError("");
    setMessage("");
    try {
      await saveAdminCategory(auth.accessToken, categoryForm);
      setCategoryForm(emptyCategoryForm);
      setMessage("Đã lưu nhóm phản ánh.");
      await loadCatalogs();
    } catch (saveError) {
      setError(saveError.message || "Không lưu được nhóm phản ánh.");
    } finally {
      setSavingTarget("");
    }
  }

  async function submitArea(event) {
    event.preventDefault();
    if (!areaForm.name.trim()) {
      setError("Vui lòng nhập tên khu vực.");
      return;
    }

    setSavingTarget("area-form");
    setError("");
    setMessage("");
    try {
      await saveAdminArea(auth.accessToken, areaForm);
      setAreaForm(emptyAreaForm);
      setMessage("Đã lưu khu vực.");
      await loadCatalogs();
    } catch (saveError) {
      setError(saveError.message || "Không lưu được khu vực.");
    } finally {
      setSavingTarget("");
    }
  }

  async function toggleCategory(category) {
    setSavingTarget(`category-${category.id}`);
    setError("");
    setMessage("");
    try {
      await saveAdminCategory(auth.accessToken, { ...category, is_active: !category.is_active });
      setMessage(category.is_active ? "Đã tắt nhóm phản ánh." : "Đã bật nhóm phản ánh.");
      await loadCatalogs();
    } catch (saveError) {
      setError(saveError.message || "Không cập nhật được nhóm phản ánh.");
    } finally {
      setSavingTarget("");
    }
  }

  async function toggleArea(area) {
    setSavingTarget(`area-${area.id}`);
    setError("");
    setMessage("");
    try {
      await saveAdminArea(auth.accessToken, { ...area, is_active: !area.is_active });
      setMessage(area.is_active ? "Đã tắt khu vực." : "Đã bật khu vực.");
      await loadCatalogs();
    } catch (saveError) {
      setError(saveError.message || "Không cập nhật được khu vực.");
    } finally {
      setSavingTarget("");
    }
  }

  return (
    <>
      <section className="admin-section-heading">
        <p className="eyebrow">Danh mục</p>
        <h1>Quản lý danh mục</h1>
        <p>Thêm, sửa, bật/tắt và sắp xếp nhóm phản ánh, khu vực.</p>
      </section>

      {isLoading && <div className="form-status">Đang tải danh mục...</div>}
      {error && <div className="form-error">{error}</div>}
      {message && <div className="form-status">{message}</div>}

      <section className="catalog-grid">
        <article className="admin-card catalog-panel">
          <div className="admin-card-title">
            <p className="eyebrow">Categories</p>
            <h2>NHÓM PHẢN ÁNH</h2>
          </div>

          <form className="catalog-form" onSubmit={submitCategory}>
            <label>
              <span>Tên nhóm</span>
              <input
                type="text"
                value={categoryForm.name}
                onChange={(event) => updateCategoryField("name", event.target.value)}
              />
            </label>
            <label>
              <span>Icon</span>
              <input
                type="text"
                value={categoryForm.icon}
                placeholder="Ví dụ: traffic"
                onChange={(event) => updateCategoryField("icon", event.target.value)}
              />
            </label>
            <label>
              <span>Thứ tự</span>
              <input
                type="number"
                min="0"
                value={categoryForm.display_order}
                onChange={(event) => updateCategoryField("display_order", event.target.value)}
              />
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={categoryForm.is_active}
                onChange={(event) => updateCategoryField("is_active", event.target.checked)}
              />
              <span>Đang bật</span>
            </label>
            <div className="catalog-actions">
              <button className="primary-action" type="submit" disabled={Boolean(savingTarget)}>
                {savingTarget === "category-form" ? "Đang lưu..." : categoryForm.id ? "Lưu nhóm" : "Thêm nhóm"}
              </button>
              {categoryForm.id && (
                <button className="secondary-action" type="button" onClick={() => setCategoryForm(emptyCategoryForm)}>
                  Hủy sửa
                </button>
              )}
            </div>
          </form>

          <CatalogTable
            type="category"
            items={categories}
            onEdit={editCategory}
            onToggle={toggleCategory}
            savingTarget={savingTarget}
          />
        </article>

        <article className="admin-card catalog-panel">
          <div className="admin-card-title">
            <p className="eyebrow">Areas</p>
            <h2>KHU VỰC</h2>
          </div>

          <form className="catalog-form" onSubmit={submitArea}>
            <label>
              <span>Tên khu vực</span>
              <input
                type="text"
                value={areaForm.name}
                onChange={(event) => updateAreaField("name", event.target.value)}
              />
            </label>
            <label>
              <span>Thứ tự</span>
              <input
                type="number"
                min="0"
                value={areaForm.display_order}
                onChange={(event) => updateAreaField("display_order", event.target.value)}
              />
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={areaForm.is_active}
                onChange={(event) => updateAreaField("is_active", event.target.checked)}
              />
              <span>Đang bật</span>
            </label>
            <div className="catalog-actions">
              <button className="primary-action" type="submit" disabled={Boolean(savingTarget)}>
                {savingTarget === "area-form" ? "Đang lưu..." : areaForm.id ? "Lưu khu vực" : "Thêm khu vực"}
              </button>
              {areaForm.id && (
                <button className="secondary-action" type="button" onClick={() => setAreaForm(emptyAreaForm)}>
                  Hủy sửa
                </button>
              )}
            </div>
          </form>

          <CatalogTable
            type="area"
            items={areas}
            onEdit={editArea}
            onToggle={toggleArea}
            savingTarget={savingTarget}
          />
        </article>
      </section>
    </>
  );
}

function CatalogTable({ type, items, onEdit, onToggle, savingTarget }) {
  const togglePrefix = type === "category" ? "category" : "area";

  return (
    <div className="admin-table-wrap">
      <table className="admin-table catalog-table">
        <thead>
          <tr>
            <th>Tên</th>
            {type === "category" && <th>Icon</th>}
            <th>Thứ tự</th>
            <th>Trạng thái</th>
            <th>Đang dùng</th>
            <th>Thao tác</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 && (
            <tr>
              <td colSpan={type === "category" ? "6" : "5"}>Chưa có dữ liệu.</td>
            </tr>
          )}
          {items.map((item) => (
            <tr key={item.id}>
              <td>
                <strong>{item.name}</strong>
              </td>
              {type === "category" && <td>{item.icon || "Không có"}</td>}
              <td>{item.display_order}</td>
              <td>
                <span className={`status-pill ${item.is_active ? "active" : "inactive"}`}>
                  {item.is_active ? "Đang bật" : "Đã tắt"}
                </span>
              </td>
              <td>{item.report_count}</td>
              <td>
                <div className="table-actions">
                  <button className="table-action" type="button" onClick={() => onEdit(item)}>
                    Sửa
                  </button>
                  <button
                    className="table-action"
                    type="button"
                    disabled={savingTarget === `${togglePrefix}-${item.id}`}
                    onClick={() => onToggle(item)}
                  >
                    {item.is_active ? "Tắt" : "Bật"}
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const adminRoleOptions = [
  { value: "ADMIN", label: "ADMIN" },
  { value: "RECEIVER", label: "RECEIVER" },
  { value: "HANDLER", label: "HANDLER" },
];

const emptyUserForm = {
  id: "",
  username: "",
  password: "",
  full_name: "",
  role: "RECEIVER",
  is_active: true,
};

function AdminUsersPage({ auth }) {
  const [users, setUsers] = useState([]);
  const [userForm, setUserForm] = useState(emptyUserForm);
  const [passwordForm, setPasswordForm] = useState({ userId: "", password: "" });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [savingTarget, setSavingTarget] = useState("");

  async function loadUsers() {
    setIsLoading(true);
    setError("");
    try {
      const body = await fetchAdminUsers(auth.accessToken);
      setUsers(body);
    } catch (loadError) {
      setError(loadError.message || "Không tải được danh sách tài khoản.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadUsers();
  }, [auth.accessToken]);

  function updateUserField(name, value) {
    setUserForm((current) => ({ ...current, [name]: value }));
    setError("");
    setMessage("");
  }

  function editUser(user) {
    setUserForm({
      id: user.id,
      username: user.username,
      password: "",
      full_name: user.full_name,
      role: user.role,
      is_active: user.is_active,
    });
    setPasswordForm({ userId: "", password: "" });
    setError("");
    setMessage("");
  }

  async function submitUser(event) {
    event.preventDefault();
    if (!userForm.id && !userForm.username.trim()) {
      setError("Vui lòng nhập tên đăng nhập.");
      return;
    }
    if (!userForm.full_name.trim()) {
      setError("Vui lòng nhập họ tên cán bộ.");
      return;
    }
    if (!userForm.id && userForm.password.length < 8) {
      setError("Mật khẩu tối thiểu 8 ký tự.");
      return;
    }

    setSavingTarget("user-form");
    setError("");
    setMessage("");
    try {
      if (userForm.id) {
        await updateAdminUser(auth.accessToken, userForm);
        setMessage("Đã cập nhật tài khoản.");
      } else {
        await createAdminUser(auth.accessToken, userForm);
        setMessage("Đã tạo tài khoản.");
      }
      setUserForm(emptyUserForm);
      await loadUsers();
    } catch (saveError) {
      setError(saveError.message || "Không lưu được tài khoản.");
    } finally {
      setSavingTarget("");
    }
  }

  async function toggleUser(user) {
    setSavingTarget(`user-${user.id}`);
    setError("");
    setMessage("");
    try {
      await updateAdminUser(auth.accessToken, { ...user, is_active: !user.is_active });
      setMessage(user.is_active ? "Đã tắt tài khoản." : "Đã bật tài khoản.");
      await loadUsers();
    } catch (saveError) {
      setError(saveError.message || "Không cập nhật được tài khoản.");
    } finally {
      setSavingTarget("");
    }
  }

  async function submitPassword(event) {
    event.preventDefault();
    if (!passwordForm.userId) {
      setError("Vui lòng chọn tài khoản cần đặt lại mật khẩu.");
      return;
    }
    if (passwordForm.password.length < 8) {
      setError("Mật khẩu mới tối thiểu 8 ký tự.");
      return;
    }

    setSavingTarget("password-form");
    setError("");
    setMessage("");
    try {
      await resetAdminUserPassword(auth.accessToken, passwordForm.userId, passwordForm.password);
      setPasswordForm({ userId: "", password: "" });
      setMessage("Đã đặt lại mật khẩu.");
      await loadUsers();
    } catch (saveError) {
      setError(saveError.message || "Không đặt lại được mật khẩu.");
    } finally {
      setSavingTarget("");
    }
  }

  return (
    <>
      <section className="admin-section-heading">
        <p className="eyebrow">Tài khoản</p>
        <h1>Quản lý tài khoản cán bộ</h1>
        <p>Tạo tài khoản, phân quyền, bật/tắt và đặt lại mật khẩu.</p>
      </section>

      {isLoading && <div className="form-status">Đang tải tài khoản...</div>}
      {error && <div className="form-error">{error}</div>}
      {message && <div className="form-status">{message}</div>}

      <section className="catalog-grid user-management-grid">
        <article className="admin-card catalog-panel">
          <div className="admin-card-title">
            <p className="eyebrow">Users</p>
            <h2>{userForm.id ? "SỬA TÀI KHOẢN" : "THÊM TÀI KHOẢN"}</h2>
          </div>

          <form className="catalog-form" onSubmit={submitUser}>
            <label>
              <span>Tên đăng nhập</span>
              <input
                type="text"
                value={userForm.username}
                disabled={Boolean(userForm.id)}
                onChange={(event) => updateUserField("username", event.target.value)}
              />
            </label>
            {!userForm.id && (
              <label>
                <span>Mật khẩu</span>
                <input
                  type="password"
                  value={userForm.password}
                  autoComplete="new-password"
                  onChange={(event) => updateUserField("password", event.target.value)}
                />
              </label>
            )}
            <label>
              <span>Họ tên</span>
              <input
                type="text"
                value={userForm.full_name}
                onChange={(event) => updateUserField("full_name", event.target.value)}
              />
            </label>
            <label>
              <span>Vai trò</span>
              <select value={userForm.role} onChange={(event) => updateUserField("role", event.target.value)}>
                {adminRoleOptions.map((role) => (
                  <option key={role.value} value={role.value}>
                    {role.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={userForm.is_active}
                onChange={(event) => updateUserField("is_active", event.target.checked)}
              />
              <span>Đang hoạt động</span>
            </label>
            <div className="catalog-actions">
              <button className="primary-action" type="submit" disabled={Boolean(savingTarget)}>
                {savingTarget === "user-form" ? "Đang lưu..." : userForm.id ? "Lưu tài khoản" : "Thêm tài khoản"}
              </button>
              {userForm.id && (
                <button className="secondary-action" type="button" onClick={() => setUserForm(emptyUserForm)}>
                  Hủy sửa
                </button>
              )}
            </div>
          </form>
        </article>

        <article className="admin-card catalog-panel">
          <div className="admin-card-title">
            <p className="eyebrow">Password</p>
            <h2>ĐẶT LẠI MẬT KHẨU</h2>
          </div>

          <form className="catalog-form" onSubmit={submitPassword}>
            <label>
              <span>Tài khoản</span>
              <select
                value={passwordForm.userId}
                onChange={(event) => setPasswordForm((current) => ({ ...current, userId: event.target.value }))}
              >
                <option value="">Chọn tài khoản</option>
                {users.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.username} - {user.role}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Mật khẩu mới</span>
              <input
                type="password"
                autoComplete="new-password"
                value={passwordForm.password}
                onChange={(event) => setPasswordForm((current) => ({ ...current, password: event.target.value }))}
              />
            </label>
            <div className="catalog-actions">
              <button className="primary-action" type="submit" disabled={Boolean(savingTarget)}>
                {savingTarget === "password-form" ? "Đang lưu..." : "Đặt lại mật khẩu"}
              </button>
            </div>
          </form>
        </article>
      </section>

      <section className="admin-card report-table-card">
        <div className="table-summary">
          <strong>{users.length}</strong>
          <span>tài khoản cán bộ</span>
        </div>
        <div className="admin-table-wrap">
          <table className="admin-table user-table">
            <thead>
              <tr>
                <th>Tên đăng nhập</th>
                <th>Họ tên</th>
                <th>Vai trò</th>
                <th>Trạng thái</th>
                <th>Ngày tạo</th>
                <th>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {users.length === 0 && (
                <tr>
                  <td colSpan="6">Chưa có tài khoản.</td>
                </tr>
              )}
              {users.map((user) => (
                <tr key={user.id}>
                  <td>
                    <strong>{user.username}</strong>
                  </td>
                  <td>{user.full_name}</td>
                  <td>{user.role}</td>
                  <td>
                    <span className={`status-pill ${user.is_active ? "active" : "inactive"}`}>
                      {user.is_active ? "Đang hoạt động" : "Đã tắt"}
                    </span>
                  </td>
                  <td>{formatDateTime(user.created_at)}</td>
                  <td>
                    <div className="table-actions">
                      <button className="table-action" type="button" onClick={() => editUser(user)}>
                        Sửa
                      </button>
                      <button
                        className="table-action"
                        type="button"
                        disabled={savingTarget === `user-${user.id}`}
                        onClick={() => toggleUser(user)}
                      >
                        {user.is_active ? "Tắt" : "Bật"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function AdminAuditLogsPage({ auth }) {
  const [logs, setLogs] = useState(null);
  const [filters, setFilters] = useState({
    action: "",
    entity_type: "",
    page: 1,
    page_size: 20,
  });
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;

    async function loadLogs() {
      setIsLoading(true);
      setError("");
      try {
        const body = await fetchAdminAuditLogs(auth.accessToken, filters);
        if (isMounted) setLogs(body);
      } catch (loadError) {
        if (isMounted) setError(loadError.message || "Không tải được nhật ký hệ thống.");
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }

    loadLogs();
    return () => {
      isMounted = false;
    };
  }, [auth.accessToken, filters]);

  function updateFilter(name, value) {
    setFilters((current) => ({ ...current, [name]: value, page: 1 }));
  }

  function clearFilters() {
    setFilters({ action: "", entity_type: "", page: 1, page_size: 20 });
  }

  function changePage(nextPage) {
    setFilters((current) => ({ ...current, page: nextPage }));
  }

  return (
    <>
      <section className="admin-section-heading">
        <p className="eyebrow">Nhật ký</p>
        <h1>Nhật ký hệ thống</h1>
        <p>Theo dõi thao tác quản trị, cập nhật phản ánh và thay đổi dữ liệu chính.</p>
      </section>

      <section className="admin-card report-filter-card">
        <label>
          <span>Hành động</span>
          <input
            type="text"
            placeholder="REPORT_RESOLVE, USER_UPDATE..."
            value={filters.action}
            onChange={(event) => updateFilter("action", event.target.value.toUpperCase())}
          />
        </label>
        <label>
          <span>Đối tượng</span>
          <select value={filters.entity_type} onChange={(event) => updateFilter("entity_type", event.target.value)}>
            <option value="">Tất cả</option>
            <option value="report">Phản ánh</option>
            <option value="category">Nhóm phản ánh</option>
            <option value="area">Khu vực</option>
            <option value="user">Tài khoản</option>
          </select>
        </label>
        <button className="secondary-action filter-reset" type="button" onClick={clearFilters}>
          Xóa lọc
        </button>
      </section>

      {error && <div className="form-error">{error}</div>}
      {isLoading && <div className="form-status">Đang tải nhật ký...</div>}

      {logs && (
        <section className="admin-card report-table-card">
          <div className="table-summary">
            <strong>{logs.total}</strong>
            <span>dòng nhật ký</span>
          </div>
          <div className="admin-table-wrap">
            <table className="admin-table audit-table">
              <thead>
                <tr>
                  <th>Thời gian</th>
                  <th>Người dùng</th>
                  <th>Hành động</th>
                  <th>Đối tượng</th>
                  <th>Chi tiết</th>
                </tr>
              </thead>
              <tbody>
                {logs.items.length === 0 && (
                  <tr>
                    <td colSpan="5">Chưa có nhật ký phù hợp.</td>
                  </tr>
                )}
                {logs.items.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDateTime(item.created_at)}</td>
                    <td>{item.user?.full_name || item.user?.username || "Hệ thống"}</td>
                    <td>
                      <strong>{item.action}</strong>
                    </td>
                    <td>
                      {item.entity_type}
                      {item.entity_id ? ` #${item.entity_id}` : ""}
                    </td>
                    <td>
                      <pre className="audit-details">{item.details || "Không có chi tiết."}</pre>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <button type="button" disabled={logs.page <= 1} onClick={() => changePage(logs.page - 1)}>
              Trước
            </button>
            <span>
              Trang {logs.page}/{logs.total_pages}
            </span>
            <button type="button" disabled={logs.page >= logs.total_pages} onClick={() => changePage(logs.page + 1)}>
              Sau
            </button>
          </div>
        </section>
      )}
    </>
  );
}

function AdminAttachmentImage({ auth, reportId, attachment }) {
  const [imageUrl, setImageUrl] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let isMounted = true;
    let objectUrl = "";

    async function loadImage() {
      try {
        const blob = await fetchAdminAttachmentBlob(auth.accessToken, reportId, attachment.id);
        if (!isMounted) return;
        objectUrl = URL.createObjectURL(blob);
        setImageUrl(objectUrl);
      } catch (loadError) {
        if (isMounted) setError(loadError.message || "Không tải được ảnh đính kèm.");
      }
    }

    loadImage();
    return () => {
      isMounted = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [auth.accessToken, reportId, attachment.id]);

  if (error) return <div className="form-error">{error}</div>;
  if (!imageUrl) return <div className="form-status">Đang tải ảnh...</div>;

  return (
    <figure className="admin-attachment">
      <img src={imageUrl} alt={attachment.original_filename} />
      <figcaption>
        {attachment.original_filename}
        {attachment.attachment_type && <span>{attachment.attachment_type}</span>}
      </figcaption>
    </figure>
  );
}

function DuplicateWarningPanel({ auth, report, onUpdated }) {
  const [linkingId, setLinkingId] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const links = report.duplicate_links ?? [];
  const suggested = links.filter((item) => item.status === "SUGGESTED");

  async function confirmLink(link) {
    setLinkingId(link.id);
    setMessage("");
    setError("");
    try {
      await linkAdminRelatedReport(
        auth.accessToken,
        report.id,
        link.related_report_id,
        link.reason || "Lien ket tu canh bao trung lap V2.4.",
      );
      const updated = await fetchAdminReportDetail(auth.accessToken, report.id);
      onUpdated(updated);
      setMessage("Đã liên kết phản ánh liên quan.");
    } catch (linkError) {
      setError(linkError.message || "Không liên kết được phản ánh.");
    } finally {
      setLinkingId("");
    }
  }

  if (links.length === 0) return null;

  return (
    <section className="admin-card duplicate-warning-card">
      <div className="admin-card-title">
        <p className="eyebrow">Cảnh báo</p>
        <h2>PHẢN ÁNH CÓ KHẢ NĂNG TRÙNG</h2>
      </div>
      {suggested.length > 0 && (
        <p className="admin-muted">Hệ thống chỉ cảnh báo, không tự động gộp hoặc xóa phản ánh.</p>
      )}
      {message && <div className="form-status">{message}</div>}
      {error && <div className="form-error">{error}</div>}
      <ul className="duplicate-link-list">
        {links.map((link) => (
          <li key={link.id}>
            <div>
              <strong>{link.related_tracking_code}</strong>
              <span className={`status-pill ${link.related_status.toLowerCase()}`}>
                {statusLabels[link.related_status] || link.related_status}
              </span>
            </div>
            <p>{link.reason || "Có dữ liệu tương đồng với phản ánh này."}</p>
            {Number.isFinite(Number(link.score)) && <small>Điểm cảnh báo: {Number(link.score).toFixed(2)}</small>}
            {link.status === "SUGGESTED" ? (
              <button
                className="secondary-action"
                type="button"
                disabled={linkingId === link.id}
                onClick={() => confirmLink(link)}
              >
                {linkingId === link.id ? "Đang liên kết..." : "Liên kết phản ánh"}
              </button>
            ) : (
              <small>Đã liên kết</small>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ProcessingImageUploadPanel({ auth, report, onUpdated }) {
  const role = auth.user?.role;
  const canUpload = ["ADMIN", "HANDLER"].includes(role);
  const [attachmentType, setAttachmentType] = useState("AFTER");
  const [files, setFiles] = useState([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [isUploading, setIsUploading] = useState(false);

  if (!canUpload) return null;

  function handleFilesChange(event) {
    const selectedFiles = Array.from(event.target.files ?? []);
    setError("");
    setMessage("");
    if (selectedFiles.length > MAX_REPORT_IMAGES) {
      setFiles([]);
      event.target.value = "";
      setError(`Chỉ được chọn tối đa ${MAX_REPORT_IMAGES} ảnh.`);
      return;
    }
    setFiles(selectedFiles);
  }

  async function handleUpload(event) {
    event.preventDefault();
    if (files.length === 0) {
      setError("Vui lòng chọn ảnh xử lý.");
      return;
    }

    setIsUploading(true);
    setError("");
    setMessage("");
    try {
      const updated = await uploadAdminProcessingImages(auth.accessToken, report.id, attachmentType, files);
      onUpdated(updated);
      setFiles([]);
      setMessage("Đã thêm ảnh xử lý.");
    } catch (uploadError) {
      setError(uploadError.message || "Không tải được ảnh xử lý.");
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <section className="admin-card processing-image-card">
      <div className="admin-card-title">
        <p className="eyebrow">Ảnh xử lý</p>
        <h2>THÊM ẢNH TRƯỚC / SAU XỬ LÝ</h2>
      </div>
      <form className="processing-image-form" onSubmit={handleUpload}>
        <label>
          <span>Loại ảnh</span>
          <select value={attachmentType} onChange={(event) => setAttachmentType(event.target.value)}>
            <option value="BEFORE">Trước xử lý</option>
            <option value="AFTER">Sau xử lý</option>
            <option value="OTHER">Khác</option>
          </select>
        </label>
        <label>
          <span>Chọn ảnh</span>
          <input
            type="file"
            multiple
            accept="image/jpeg,image/png,image/webp,image/gif"
            onChange={handleFilesChange}
          />
        </label>
        {files.length > 0 && <p className="admin-muted">Đã chọn {files.length} ảnh.</p>}
        {message && <div className="form-status">{message}</div>}
        {error && <div className="form-error">{error}</div>}
        <button className="secondary-action" type="submit" disabled={isUploading}>
          {isUploading ? "Đang tải..." : "Thêm ảnh xử lý"}
        </button>
      </form>
    </section>
  );
}

function ReportActionPanel({ auth, report, onUpdated }) {
  const role = auth.user?.role;
  const [internalNote, setInternalNote] = useState("");
  const [publicNote, setPublicNote] = useState("");
  const [coordinationTarget, setCoordinationTarget] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [submittingAction, setSubmittingAction] = useState("");

  const hasActions =
    canReceiveReport(role, report.status) ||
    canCoordinateReport(role, report.status) ||
    canResolveReport(role, report.status) ||
    canMarkOutOfScope(role, report.status);

  async function runAction(action, successMessage) {
    if (action === "resolve" && !publicNote.trim()) {
      setError("Vui lòng nhập kết quả công khai trước khi hoàn thành.");
      return;
    }

    setSubmittingAction(action);
    setError("");
    setMessage("");
    try {
      const updated = await transitionAdminReport(auth.accessToken, report.id, action, {
        internal_note: internalNote,
        public_note: publicNote,
        coordination_target: coordinationTarget,
      });
      onUpdated(updated);
      setMessage(successMessage);
      setInternalNote("");
      setPublicNote("");
      setCoordinationTarget("");
    } catch (actionError) {
      setError(actionError.message || "Không thực hiện được thao tác.");
    } finally {
      setSubmittingAction("");
    }
  }

  if (!hasActions) {
    return (
      <section className="admin-card">
        <div className="admin-card-title">
          <p className="eyebrow">Xử lý</p>
          <h2>KHÔNG CÓ THAO TÁC PHÙ HỢP</h2>
        </div>
        <p className="admin-muted">Trạng thái hiện tại hoặc vai trò của bạn không có thao tác tiếp theo.</p>
      </section>
    );
  }

  return (
    <section className="admin-card report-action-card">
      <div className="admin-card-title">
        <p className="eyebrow">Xử lý</p>
        <h2>CẬP NHẬT PHẢN ÁNH</h2>
      </div>

      <label>
        <span>Ghi chú nội bộ</span>
        <textarea
          value={internalNote}
          placeholder="Ghi chú chỉ hiển thị trong khu vực quản trị..."
          onChange={(event) => setInternalNote(event.target.value)}
        />
      </label>

      {canCoordinateReport(role, report.status) && (
        <label>
          <span>Đầu mối/bộ phận phối hợp</span>
          <input
            type="text"
            value={coordinationTarget}
            placeholder="Ví dụ: Tổ hạ tầng, công an xã, đơn vị điện lực..."
            onChange={(event) => setCoordinationTarget(event.target.value)}
          />
        </label>
      )}

      <label>
        <span>Nội dung công khai</span>
        <textarea
          value={publicNote}
          placeholder="Nội dung người dân có thể nhìn thấy khi tra cứu..."
          onChange={(event) => setPublicNote(event.target.value)}
        />
      </label>

      {error && <div className="form-error">{error}</div>}
      {message && <div className="form-status">{message}</div>}

      <div className="report-action-buttons">
        {canReceiveReport(role, report.status) && (
          <button
            className="primary-action"
            type="button"
            disabled={Boolean(submittingAction)}
            onClick={() => runAction("receive", "Đã tiếp nhận phản ánh.")}
          >
            {submittingAction === "receive" ? "Đang xử lý..." : "TIẾP NHẬN"}
          </button>
        )}
        {canCoordinateReport(role, report.status) && (
          <button
            className="primary-action"
            type="button"
            disabled={Boolean(submittingAction)}
            onClick={() => runAction("coordinate", "Đã chuyển/phối hợp phản ánh.")}
          >
            {submittingAction === "coordinate" ? "Đang xử lý..." : "CHUYỂN / PHỐI HỢP"}
          </button>
        )}
        {canResolveReport(role, report.status) && (
          <button
            className="primary-action"
            type="button"
            disabled={Boolean(submittingAction)}
            onClick={() => runAction("resolve", "Đã cập nhật hoàn thành xử lý.")}
          >
            {submittingAction === "resolve" ? "Đang xử lý..." : "ĐÃ XỬ LÝ"}
          </button>
        )}
        {canMarkOutOfScope(role, report.status) && (
          <button
            className="secondary-action danger-action"
            type="button"
            disabled={Boolean(submittingAction)}
            onClick={() => runAction("out-of-scope", "Đã chuyển ngoài phạm vi tiếp nhận.")}
          >
            {submittingAction === "out-of-scope" ? "Đang xử lý..." : "KHÔNG THUỘC PHẠM VI"}
          </button>
        )}
      </div>
    </section>
  );
}

function ReportTechnicalMetadataPanel({ auth, reportId, technical, isLoading, error, onReload }) {
  const metadata = technical?.technical_metadata || {};
  const capturedAt = technical?.client_submitted_at || metadata.observed_at;
  const activeBlocks = technical?.active_source_blocks || [];
  const fingerprintBlocked = activeBlocks.find((item) => item.source_type === "FINGERPRINT" && item.is_active);
  const [actionError, setActionError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [submittingAction, setSubmittingAction] = useState("");

  async function runSourceAction(action) {
    setActionError("");
    setActionMessage("");
    setSubmittingAction(action);
    try {
      if (action === "block") {
        await blockAdminReportSource(auth.accessToken, reportId, "FINGERPRINT", "Chan nguon gui co dau hieu spam.");
        setActionMessage("Đã chặn nguồn gửi theo fingerprint.");
      } else if (fingerprintBlocked) {
        await unblockAdminReportSource(auth.accessToken, fingerprintBlocked.id);
        setActionMessage("Đã bỏ chặn nguồn gửi.");
      }
      await onReload();
    } catch (actionLoadError) {
      setActionError(actionLoadError.message || "Không thực hiện được thao tác nguồn gửi.");
    } finally {
      setSubmittingAction("");
    }
  }

  return (
    <section className="admin-card technical-card">
      <details>
        <summary>
          <span className="eyebrow">Nội bộ</span>
          <strong>THÔNG TIN KỸ THUẬT</strong>
        </summary>

        {isLoading && <p className="admin-muted">Đang tải thông tin kỹ thuật...</p>}
        {error && <div className="form-error">{error}</div>}
        {!isLoading && !error && (
          <dl className="technical-metadata-list">
            <div>
              <dt>IP client</dt>
              <dd>{formatTechnicalValue(metadata.client_ip)}</dd>
            </div>
            <div>
              <dt>Source port</dt>
              <dd>{formatTechnicalValue(metadata.observed_source_port)}</dd>
            </div>
            <div>
              <dt>User-Agent</dt>
              <dd>{formatTechnicalValue(metadata.user_agent)}</dd>
            </div>
            <div>
              <dt>Thời gian ghi nhận metadata</dt>
              <dd>{formatTechnicalTime(capturedAt)}</dd>
            </div>
          </dl>
        )}
        {!isLoading && !error && (
          <div className="source-block-panel">
            <div>
              <span>Trạng thái nguồn gửi</span>
              <strong>{fingerprintBlocked ? "Đang bị chặn" : "Chưa chặn"}</strong>
            </div>
            {activeBlocks.length > 0 && (
              <ul>
                {activeBlocks.map((item) => (
                  <li key={item.id}>
                    {item.source_type}: {item.reason || "Không ghi chú"}
                  </li>
                ))}
              </ul>
            )}
            {actionError && <div className="form-error">{actionError}</div>}
            {actionMessage && <div className="form-status">{actionMessage}</div>}
            <div className="report-action-buttons">
              {!fingerprintBlocked && (
                <button
                  className="secondary-action danger-action"
                  type="button"
                  disabled={Boolean(submittingAction) || !technical?.request_fingerprint_hash}
                  onClick={() => runSourceAction("block")}
                >
                  {submittingAction === "block" ? "Đang chặn..." : "CHẶN NGUỒN NÀY"}
                </button>
              )}
              {fingerprintBlocked && (
                <button
                  className="secondary-action"
                  type="button"
                  disabled={Boolean(submittingAction)}
                  onClick={() => runSourceAction("unblock")}
                >
                  {submittingAction === "unblock" ? "Đang bỏ chặn..." : "BỎ CHẶN NGUỒN NÀY"}
                </button>
              )}
            </div>
          </div>
        )}
      </details>
    </section>
  );
}

function AdminReportDetailPage({ auth }) {
  const { id } = useParams();
  const [report, setReport] = useState(null);
  const [technical, setTechnical] = useState(null);
  const [technicalError, setTechnicalError] = useState("");
  const [isTechnicalLoading, setIsTechnicalLoading] = useState(false);
  const [technicalReloadKey, setTechnicalReloadKey] = useState(0);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const canViewTechnicalMetadata = auth.user?.role === "ADMIN";

  useEffect(() => {
    let isMounted = true;

    async function loadReport() {
      setIsLoading(true);
      setError("");
      try {
        const body = await fetchAdminReportDetail(auth.accessToken, id);
        if (!isMounted) return;
        setReport(body);
      } catch (loadError) {
        if (isMounted) setError(loadError.message || "Không tải được chi tiết phản ánh.");
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }

    loadReport();
    return () => {
      isMounted = false;
    };
  }, [auth.accessToken, id]);

  async function loadTechnicalMetadata({ isMounted = () => true } = {}) {
      if (!canViewTechnicalMetadata) {
        setTechnical(null);
        setTechnicalError("");
        setIsTechnicalLoading(false);
        return;
      }

      setIsTechnicalLoading(true);
      setTechnicalError("");
      try {
        const body = await fetchAdminReportTechnical(auth.accessToken, id);
        if (!isMounted()) return;
        setTechnical(body);
      } catch (loadError) {
        if (isMounted()) {
          setTechnical(null);
          setTechnicalError(loadError.message || "Không tải được thông tin kỹ thuật.");
        }
      } finally {
        if (isMounted()) setIsTechnicalLoading(false);
      }
    }

  useEffect(() => {
    let isMounted = true;

    loadTechnicalMetadata({ isMounted: () => isMounted });
    return () => {
      isMounted = false;
    };
  }, [auth.accessToken, canViewTechnicalMetadata, id, technicalReloadKey]);

  return (
    <>
      <section className="admin-section-heading">
        <p className="eyebrow">Phản ánh</p>
        <h1>Chi tiết phản ánh</h1>
        <p>Xem nội dung, ảnh và cập nhật tiến trình xử lý.</p>
      </section>

      <Link className="secondary-action admin-back-link" to="/admin/reports">
        Quay lại danh sách
      </Link>

      {isLoading && <div className="form-status">Đang tải chi tiết phản ánh...</div>}
      {error && <div className="form-error">{error}</div>}

      {report && (
        <>
          <section className="admin-card report-detail-card">
            <div className="result-title">
              <span>Mã phản ánh</span>
              <strong>{report.tracking_code}</strong>
            </div>

            <dl className="report-summary">
              <div>
                <dt>Thời gian</dt>
                <dd>{formatDateTime(report.created_at)}</dd>
              </div>
              <div>
                <dt>Cập nhật</dt>
                <dd>{formatDateTime(report.updated_at)}</dd>
              </div>
              <div>
                <dt>Nhóm</dt>
                <dd>{report.category}</dd>
              </div>
              <div>
                <dt>Khu vực</dt>
                <dd>{report.area || "Chưa xác định"}</dd>
              </div>
              <div>
                <dt>Trạng thái</dt>
                <dd>
                  <span className={`status-pill ${report.status.toLowerCase()}`}>
                    {statusLabels[report.status] || report.status}
                  </span>
                </dd>
              </div>
            </dl>

            <div className="report-description">
              <span>Mô tả</span>
              <p>{report.description}</p>
            </div>

            <div className="report-description">
              <span>Ảnh</span>
              {report.attachments.length === 0 && <p>Không có ảnh đính kèm.</p>}
              {report.attachments.map((attachment) => (
                <AdminAttachmentImage
                  key={attachment.id}
                  auth={auth}
                  reportId={report.id}
                  attachment={attachment}
                />
              ))}
            </div>
          </section>

          <DuplicateWarningPanel auth={auth} report={report} onUpdated={setReport} />

          <ProcessingImageUploadPanel auth={auth} report={report} onUpdated={setReport} />

          <ReportActionPanel auth={auth} report={report} onUpdated={setReport} />

          <section className="admin-card history-card">
            <div className="admin-card-title">
              <p className="eyebrow">Lịch sử</p>
              <h2>LỊCH SỬ XỬ LÝ</h2>
            </div>
            {report.status_history.length === 0 && <p className="admin-muted">Chưa có lịch sử xử lý.</p>}
            {report.status_history.length > 0 && (
              <ol className="admin-history-list">
                {report.status_history.map((item) => (
                  <li key={item.id}>
                    <span className={`status-pill ${item.new_status.toLowerCase()}`}>
                      {statusLabels[item.new_status] || item.new_status}
                    </span>
                    <strong>{formatDateTime(item.created_at)}</strong>
                    <p>
                      {item.old_status ? `${statusLabels[item.old_status] || item.old_status} -> ` : ""}
                      {statusLabels[item.new_status] || item.new_status}
                    </p>
                    {item.changed_by && <p>Người cập nhật: {item.changed_by.full_name || item.changed_by.username}</p>}
                    {item.public_note && <p>Công khai: {item.public_note}</p>}
                    {item.internal_note && <p>Nội bộ: {item.internal_note}</p>}
                  </li>
                ))}
              </ol>
            )}
          </section>

          {canViewTechnicalMetadata && (
            <ReportTechnicalMetadataPanel
              auth={auth}
              reportId={id}
              technical={technical}
              isLoading={isTechnicalLoading}
              error={technicalError}
              onReload={() => {
                setTechnicalReloadKey((current) => current + 1);
              }}
            />
          )}
        </>
      )}
    </>
  );
}

function InstallPrompt() {
  const location = useLocation();
  const [installEvent, setInstallEvent] = useState(null);
  const [isInstalling, setIsInstalling] = useState(false);
  const isAdminPath = location.pathname.startsWith("/admin");

  useEffect(() => {
    function handleBeforeInstallPrompt(event) {
      event.preventDefault();
      setInstallEvent(event);
    }

    window.addEventListener("beforeinstallprompt", handleBeforeInstallPrompt);
    return () => {
      window.removeEventListener("beforeinstallprompt", handleBeforeInstallPrompt);
    };
  }, []);

  async function handleInstall() {
    if (!installEvent || isInstalling) return;
    setIsInstalling(true);
    try {
      installEvent.prompt();
      await installEvent.userChoice;
      setInstallEvent(null);
    } finally {
      setIsInstalling(false);
    }
  }

  if (!installEvent || isAdminPath) return null;

  return (
    <aside className="install-prompt" aria-label="Cài ứng dụng">
      <span>Yên Trường 360</span>
      <button type="button" onClick={handleInstall} disabled={isInstalling}>
        {isInstalling ? "Đang mở..." : "Thêm vào màn hình chính"}
      </button>
    </aside>
  );
}

function App() {
  const [auth, setAuth] = useState(() => loadStoredAuth());

  useEffect(() => {
    if (!("serviceWorker" in navigator) || !import.meta.env.PROD) return;
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }, []);

  function handleLogin(result) {
    const nextAuth = {
      accessToken: result.access_token,
      expiresIn: result.expires_in,
      user: result.user,
    };
    setAuth(nextAuth);
    storeAuth(nextAuth);
  }

  function handleLogout() {
    setAuth(null);
    storeAuth(null);
  }

  return (
    <div className="app-shell">
      <Header />
      <InstallPrompt />

      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/phan-anh" element={<CitizenReportPage />} />
        <Route path="/tra-cuu" element={<LookupPage />} />
        <Route path="/admin/login" element={<AdminLoginPage auth={auth} onLogin={handleLogin} />} />
        <Route path="/admin" element={<Navigate to="/admin/dashboard" replace />} />
        <Route
          path="/admin/dashboard"
          element={
            <ProtectedAdminRoute auth={auth}>
              <AdminLayout auth={auth} onLogout={handleLogout}>
                <DashboardPage auth={auth} />
              </AdminLayout>
            </ProtectedAdminRoute>
          }
        />
        <Route
          path="/admin/reports"
          element={
            <ProtectedAdminRoute auth={auth}>
              <AdminLayout auth={auth} onLogout={handleLogout}>
                <AdminReportsPage auth={auth} />
              </AdminLayout>
            </ProtectedAdminRoute>
          }
        />
        <Route
          path="/admin/reports/:id"
          element={
            <ProtectedAdminRoute auth={auth}>
              <AdminLayout auth={auth} onLogout={handleLogout}>
                <AdminReportDetailPage auth={auth} />
              </AdminLayout>
            </ProtectedAdminRoute>
          }
        />
        <Route
          path="/admin/statistics"
          element={
            <ProtectedAdminRoute auth={auth}>
              <AdminLayout auth={auth} onLogout={handleLogout}>
                <AdminStatisticsPage auth={auth} />
              </AdminLayout>
            </ProtectedAdminRoute>
          }
        />
        <Route
          path="/admin/categories"
          element={
            <ProtectedAdminRoute auth={auth}>
              <AdminLayout auth={auth} onLogout={handleLogout}>
                <AdminCatalogsPage auth={auth} />
              </AdminLayout>
            </ProtectedAdminRoute>
          }
        />
        <Route
          path="/admin/users"
          element={
            <ProtectedAdminRoute auth={auth}>
              <AdminLayout auth={auth} onLogout={handleLogout}>
                <AdminUsersPage auth={auth} />
              </AdminLayout>
            </ProtectedAdminRoute>
          }
        />
        <Route
          path="/admin/audit-logs"
          element={
            <ProtectedAdminRoute auth={auth}>
              <AdminLayout auth={auth} onLogout={handleLogout}>
                <AdminAuditLogsPage auth={auth} />
              </AdminLayout>
            </ProtectedAdminRoute>
          }
        />
      </Routes>
    </div>
  );
}

export default App;
