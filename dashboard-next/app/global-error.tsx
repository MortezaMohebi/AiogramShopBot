"use client";

/**
 * Last-resort failure screen if the root layout itself crashes.
 *
 * This boundary must render <html> and <body> without importing the
 * application providers, theme or server-only data dependencies.
 */
export default function GlobalError() {
  return (
    <html lang="fa" dir="rtl">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          background: "#0e141b",
          color: "#e8eef3",
          fontFamily: "Tahoma, sans-serif",
          display: "grid",
          placeItems: "center",
          padding: "24px",
        }}
      >
        <main style={{ maxWidth: 540, width: "100%", lineHeight: 2 }}>
          <h1 style={{ fontSize: 24 }}>خطا در بارگذاری داشبورد</h1>
          <p role="alert">
            صفحه در دسترس نیست. دوباره بارگذاری کنید.
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            <button
              type="button"
              onClick={() => window.location.reload()}
              style={{
                padding: "8px 20px",
                borderRadius: 8,
                cursor: "pointer",
              }}
            >
              بارگذاری دوباره
            </button>
            <a
              href="/login"
              style={{ color: "#9cdbd0", padding: "8px 4px" }}
            >
              صفحهٔ ورود
            </a>
          </div>
        </main>
      </body>
    </html>
  );
}
