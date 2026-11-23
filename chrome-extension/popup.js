/**
 * Any URL Downloader - Cookie Exporter (Manifest V3)
 * Formats browser cookies strictly to Netscape HTTP Cookie File standard
 * Supports download, clipboard copy, and direct Telegram Bot upload via FormData.
 */

document.addEventListener("DOMContentLoaded", async () => {
  // Elements
  const activeDomainEl = document.getElementById("active-domain");
  const cookieBadgeEl = document.getElementById("cookie-badge");
  const rootDomainNameEl = document.getElementById("root-domain-name");
  const includeSubdomainsEl = document.getElementById("include-subdomains");

  const btnDownload = document.getElementById("btn-download");
  const btnCopy = document.getElementById("btn-copy");
  const btnTelegram = document.getElementById("btn-telegram");

  const settingsToggle = document.getElementById("settings-toggle");
  const settingsPanel = document.getElementById("settings-panel");
  const settingsChevron = document.getElementById("settings-chevron");
  const botTokenInput = document.getElementById("bot-token");
  const chatIdInput = document.getElementById("chat-id");
  const btnSaveSettings = document.getElementById("btn-save-settings");

  const statusBanner = document.getElementById("status-banner");
  const statusIcon = document.getElementById("status-icon");
  const statusText = document.getElementById("status-text");

  let currentTab = null;
  let currentHostname = "";
  let currentRootDomain = "";
  let cachedCookies = [];

  // 1. Load saved settings from chrome.storage.local
  if (chrome.storage && chrome.storage.local) {
    chrome.storage.local.get(["botToken", "chatId", "includeSubdomains"], (res) => {
      if (res.botToken) botTokenInput.value = res.botToken;
      if (res.chatId) chatIdInput.value = res.chatId;
      if (res.includeSubdomains !== undefined) {
        includeSubdomainsEl.checked = res.includeSubdomains;
      }
    });
  }

  // 2. Settings Toggle
  settingsToggle.addEventListener("click", () => {
    const isCollapsed = settingsPanel.classList.toggle("collapsed");
    settingsChevron.classList.toggle("open", !isCollapsed);
  });

  // 3. Save Settings Button
  btnSaveSettings.addEventListener("click", () => {
    const token = botTokenInput.value.trim();
    const chat = chatIdInput.value.trim();
    if (chrome.storage && chrome.storage.local) {
      chrome.storage.local.set({ botToken: token, chatId: chat }, () => {
        showStatus("✅ Settings saved locally!", "success");
      });
    }
  });

  includeSubdomainsEl.addEventListener("change", () => {
    if (chrome.storage && chrome.storage.local) {
      chrome.storage.local.set({ includeSubdomains: includeSubdomainsEl.checked });
    }
    refreshCookies();
  });

  // 4. Extract root domain helper
  function getRootDomain(hostname) {
    if (!hostname) return "";
    // If it's an IP address or localhost
    if (/^(?:\d{1,3}\.){3}\d{1,3}$/.test(hostname) || hostname === "localhost") {
      return hostname;
    }
    const parts = hostname.split(".");
    if (parts.length <= 2) return hostname;

    const secondLast = parts[parts.length - 2].toLowerCase();
    // Known two-part TLD suffixes like .co.uk, .com.au, .edu.lk, etc.
    const twoPartTlds = ["co", "com", "edu", "gov", "org", "net", "ac", "sch"];
    if (twoPartTlds.includes(secondLast) && parts.length >= 3) {
      return parts.slice(-3).join(".");
    }
    return parts.slice(-2).join(".");
  }

  // 5. Query active tab and fetch cookies
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tabs || tabs.length === 0) {
      showStatus("⚠️ No active browser tab detected.", "error");
      return;
    }
    currentTab = tabs[0];
    if (!currentTab.url || currentTab.url.startsWith("chrome://") || currentTab.url.startsWith("edge://") || currentTab.url.startsWith("about:")) {
      activeDomainEl.textContent = "Browser Internal Page";
      cookieBadgeEl.textContent = "0 cookies";
      cookieBadgeEl.classList.add("zero");
      btnDownload.disabled = true;
      btnCopy.disabled = true;
      btnTelegram.disabled = true;
      showStatus("ℹ️ Cannot extract cookies from browser internal pages.", "error");
      return;
    }

    const urlObj = new URL(currentTab.url);
    currentHostname = urlObj.hostname;
    currentRootDomain = getRootDomain(currentHostname);

    activeDomainEl.textContent = currentHostname;
    rootDomainNameEl.textContent = `.${currentRootDomain}`;

    await refreshCookies();
  } catch (err) {
    showStatus(`⚠️ Failed to inspect active tab: ${err.message}`, "error");
  }

  // 6. Fetch and filter cookies
  async function refreshCookies() {
    if (!currentHostname) return;

    try {
      const matchAllSubdomains = includeSubdomainsEl.checked;
      const cookieMap = new Map();

      // Fetch cookies bound to exact active tab URL
      const urlCookies = await chrome.cookies.getAll({ url: currentTab.url });
      for (const c of urlCookies) {
        cookieMap.set(`${c.domain}|${c.path}|${c.name}`, c);
      }

      // Fetch cookies bound to domain
      const targetDomain = matchAllSubdomains ? currentRootDomain : currentHostname;
      const domainCookies = await chrome.cookies.getAll({ domain: targetDomain });
      for (const c of domainCookies) {
        cookieMap.set(`${c.domain}|${c.path}|${c.name}`, c);
      }

      // If matching subdomains, also fetch with leading dot
      if (matchAllSubdomains && !currentRootDomain.startsWith(".")) {
        const dotCookies = await chrome.cookies.getAll({ domain: `.${currentRootDomain}` });
        for (const c of dotCookies) {
          cookieMap.set(`${c.domain}|${c.path}|${c.name}`, c);
        }
      }

      cachedCookies = Array.from(cookieMap.values());

      // Sort by domain then name
      cachedCookies.sort((a, b) => {
        if (a.domain !== b.domain) return a.domain.localeCompare(b.domain);
        return a.name.localeCompare(b.name);
      });

      cookieBadgeEl.textContent = `${cachedCookies.length} cookie${cachedCookies.length === 1 ? "" : "s"}`;
      if (cachedCookies.length === 0) {
        cookieBadgeEl.classList.add("zero");
        btnDownload.disabled = true;
        btnCopy.disabled = true;
        btnTelegram.disabled = true;
        showStatus(`ℹ️ No cookies found for ${currentHostname}. Ensure you are logged in.`, "error");
      } else {
        cookieBadgeEl.classList.remove("zero");
        btnDownload.disabled = false;
        btnCopy.disabled = false;
        btnTelegram.disabled = false;
      }
    } catch (err) {
      showStatus(`⚠️ Cookie retrieval error: ${err.message}`, "error");
    }
  }

  // 7. Format cookies into standard Netscape HTTP Cookie File format
  function formatNetscape(cookies) {
    let out = "# Netscape HTTP Cookie File\n";
    out += "# http://curl.haxx.se/rfc/cookie_spec.html\n";
    out += "# This is a generated file!  Do not edit.\n\n";

    for (const c of cookies) {
      const domain = c.domain;
      const includeSubdomains = domain.startsWith(".") ? "TRUE" : "FALSE";
      const path = c.path || "/";
      const secure = c.secure ? "TRUE" : "FALSE";
      // Expiry: for session cookies without expirationDate, use 1 year future timestamp
      const expiry = c.expirationDate
        ? Math.round(c.expirationDate)
        : Math.floor(Date.now() / 1000) + 86400 * 365;

      out += `${domain}\t${includeSubdomains}\t${path}\t${secure}\t${expiry}\t${c.name}\t${c.value}\n`;
    }
    return out;
  }

  // 8. Download cookies.txt
  btnDownload.addEventListener("click", () => {
    if (!cachedCookies || cachedCookies.length === 0) return;

    try {
      const netscapeText = formatNetscape(cachedCookies);
      const blob = new Blob([netscapeText], { type: "text/plain;charset=utf-8" });
      const blobUrl = URL.createObjectURL(blob);

      chrome.downloads.download({
        url: blobUrl,
        filename: "cookies.txt",
        saveAs: false,
      }, (downloadId) => {
        if (chrome.runtime.lastError) {
          showStatus(`⚠️ Download error: ${chrome.runtime.lastError.message}`, "error");
        } else {
          showStatus("✅ cookies.txt downloaded successfully!", "success");
        }
      });
    } catch (err) {
      showStatus(`⚠️ Download failed: ${err.message}`, "error");
    }
  });

  // 9. Copy to Clipboard
  btnCopy.addEventListener("click", async () => {
    if (!cachedCookies || cachedCookies.length === 0) return;

    try {
      const netscapeText = formatNetscape(cachedCookies);
      await navigator.clipboard.writeText(netscapeText);
      showStatus("📋 Formatted Netscape cookies copied to clipboard!", "success");
    } catch (err) {
      showStatus(`⚠️ Failed to copy: ${err.message}`, "error");
    }
  });

  // 10. Send directly to Telegram Bot via Bot API sendDocument
  btnTelegram.addEventListener("click", async () => {
    if (!cachedCookies || cachedCookies.length === 0) return;

    const botToken = botTokenInput.value.trim();
    const chatId = chatIdInput.value.trim();

    if (!botToken || !chatId) {
      // Expand settings panel to guide user
      settingsPanel.classList.remove("collapsed");
      settingsChevron.classList.add("open");
      showStatus("⚙️ Please enter your Bot Token & Chat ID in Settings below.", "error");
      if (!botToken) botTokenInput.focus();
      else chatIdInput.focus();
      return;
    }

    // Save tokens if not already saved
    if (chrome.storage && chrome.storage.local) {
      chrome.storage.local.set({ botToken, chatId });
    }

    btnTelegram.disabled = true;
    showStatus("⏳ Sending cookies.txt to Telegram bot...", "loading");

    try {
      const netscapeText = formatNetscape(cachedCookies);
      const blob = new Blob([netscapeText], { type: "text/plain;charset=utf-8" });

      const formData = new FormData();
      formData.append("chat_id", chatId);
      formData.append("document", blob, "cookies.txt");
      formData.append(
        "caption",
        `🍪 **Netscape cookies.txt**\n` +
        `• **Domain:** \`${currentHostname}\`\n` +
        `• **Cookies:** \`${cachedCookies.length}\`\n` +
        `• **Exported:** \`${new Date().toISOString()}\``
      );

      const endpoint = `https://api.telegram.org/bot${botToken}/sendDocument`;
      const response = await fetch(endpoint, {
        method: "POST",
        body: formData,
      });

      const resData = await response.json();
      if (resData.ok) {
        showStatus("🚀 cookies.txt sent directly to your Telegram bot!", "success");
      } else {
        const desc = resData.description || "Failed to upload document.";
        showStatus(`❌ Telegram error: ${desc}`, "error");
      }
    } catch (err) {
      showStatus(`⚠️ Connection error: ${err.message}`, "error");
    } finally {
      btnTelegram.disabled = false;
    }
  });

  // 11. Helper: Status Banner
  function showStatus(message, type) {
    statusBanner.className = `status-banner ${type}`;
    statusText.textContent = message;

    if (type === "success") {
      statusIcon.textContent = "✅";
    } else if (type === "error") {
      statusIcon.textContent = "⚠️";
    } else if (type === "loading") {
      statusIcon.textContent = "⏳";
    } else {
      statusIcon.textContent = "ℹ️";
    }
  }
});
