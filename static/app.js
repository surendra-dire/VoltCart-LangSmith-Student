(() => {
  "use strict";

  const ACTIVE_ORDER_STATUSES = new Set(["Confirmed", "Processing", "Packed", "Shipped", "Out for delivery"]);
  const STATUS_STEPS = ["Confirmed", "Packed", "Shipped", "Delivered"];
  const CATEGORY_ICONS = {
    All: "\u2726",
    Smartphones: "\u{1F4F1}",
    Laptops: "\u{1F4BB}",
    Audio: "\u{1F3A7}",
    Wearables: "\u231A",
    "TV & Smart Home": "\u{1F4FA}",
    "Gaming & Accessories": "\u{1F3AE}",
    Tablets: "\u{1F4F1}",
  };

  const state = {
    config: {},
    products: [],
    orders: [],
    cart: { items: [], item_count: 0, total: 0 },
    preferences: {},
    user: null,
    authMode: "login",
    category: "All",
    query: "",
    maxPrice: null,
    sort: "featured",
    orderFilter: "all",
    chatBusy: false,
    sessionId: getOrCreateSessionId(),
    lastFocus: null,
  };

  const refs = {};

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    [
      "headerSearchForm", "globalSearch", "searchClear", "headerAgentButton", "openOrdersButton",
      "headerUserName", "ordersCount", "heroProductCount", "heroDealCount", "exploreDealsButton",
      "askAgentHeroButton", "categoryPills", "resultsSummary", "priceFilter", "sortProducts",
      "clearFilters", "productGrid", "storeLayout", "agentPanel", "agentMessages", "suggestedPrompts",
      "agentForm", "agentInput", "sendAgentButton", "agentModeLabel", "resetDemoButton",
      "collapseAgentButton", "closeAgentButton", "agentFab", "mobileAgentBackdrop", "ordersLayer",
      "ordersDrawer", "drawerUserName", "orderTabs", "ordersList", "askAboutOrdersButton",
      "productModalLayer", "productModal", "productModalContent", "toastRegion", "welcomeUserName",
      "openCartButton", "cartCount", "cartLayer", "cartDrawer", "cartItems", "cartTotal", "checkoutWithAgentButton",
      "accountButton", "accountName", "accountLayer", "accountDetails", "closeAccountButton", "logoutButton",
      "authLayer", "authForm", "authTitle", "authSubtitle", "authName", "authEmail", "authPhone", "authPassword", "authError", "authSubmit", "forgotPasswordButton",
      "openInsightsButton", "insightsLayer", "closeInsightsButton", "traceMetrics", "traceList", "refreshTracesButton", "proactiveBanner",
      "preferencesForm", "preferenceEnabled", "preferenceBudget", "preferenceBrands", "preferenceExcluded", "preferenceLocation", "preferenceUrgency", "clearPreferencesButton",
    ].forEach((id) => { refs[id] = document.getElementById(id); });

    bindEvents();
    bootstrap();
  }

  async function bootstrap() {
    await Promise.allSettled([loadProducts(), loadConfig()]);
    try {
      const auth = await apiFetch("/api/auth/me");
      if (auth.authenticated) await completeSignIn(auth.user);
      else openAuth();
    } catch (error) {
      openAuth();
      showToast("Authentication unavailable", error.message, "error");
    }
  }

  function bindEvents() {
    refs.headerSearchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      setSearch(refs.globalSearch.value);
      scrollToProducts();
    });

    refs.globalSearch.addEventListener("input", () => {
      setSearch(refs.globalSearch.value);
    });

    refs.searchClear.addEventListener("click", () => {
      refs.globalSearch.value = "";
      setSearch("");
      refs.globalSearch.focus();
    });

    refs.categoryPills.addEventListener("click", (event) => {
      const button = event.target.closest("[data-category]");
      if (!button) return;
      state.category = button.dataset.category || "All";
      updateCategorySelection();
      renderProducts();
    });

    refs.priceFilter.addEventListener("change", () => {
      state.maxPrice = refs.priceFilter.value ? Number(refs.priceFilter.value) : null;
      renderProducts();
    });

    refs.sortProducts.addEventListener("change", () => {
      state.sort = refs.sortProducts.value;
      renderProducts();
    });

    refs.clearFilters.addEventListener("click", clearAllFilters);

    refs.productGrid.addEventListener("click", (event) => {
      const orderButton = event.target.closest("[data-order-product]");
      const cartButton = event.target.closest("[data-add-cart]");
      const detailsButton = event.target.closest("[data-product-details]");
      const retryButton = event.target.closest("[data-retry-products]");
      if (retryButton) {
        loadProducts();
      } else if (cartButton) {
        addToCart(cartButton.dataset.addCart);
      } else if (orderButton) {
        const product = findProduct(orderButton.dataset.orderProduct);
        if (product) orderProductWithAgent(product, false);
      } else if (detailsButton) {
        openProductModal(detailsButton.dataset.productDetails);
      }
    });

    refs.exploreDealsButton.addEventListener("click", () => {
      clearAllFilters(false);
      state.sort = "discount";
      refs.sortProducts.value = "discount";
      renderProducts();
      scrollToProducts();
    });

    refs.askAgentHeroButton.addEventListener("click", () => openAgent(true));
    refs.headerAgentButton.addEventListener("click", () => openAgent(true));
    refs.agentFab.addEventListener("click", () => openAgent(true));
    refs.closeAgentButton.addEventListener("click", closeAgent);
    refs.mobileAgentBackdrop.addEventListener("click", closeAgent);

    refs.collapseAgentButton.addEventListener("click", () => {
      const collapsed = refs.agentPanel.classList.toggle("is-collapsed");
      refs.storeLayout.classList.toggle("agent-collapsed", collapsed);
      refs.collapseAgentButton.setAttribute("aria-label", collapsed ? "Expand shopping agent" : "Collapse shopping agent");
      refs.collapseAgentButton.title = collapsed ? "Expand agent" : "Collapse agent";
      if (!collapsed) refs.agentInput.focus();
    });

    refs.agentPanel.querySelector(".agent-collapsed-content").addEventListener("click", () => {
      refs.agentPanel.classList.remove("is-collapsed");
      refs.storeLayout.classList.remove("agent-collapsed");
      refs.agentInput.focus();
    });

    refs.suggestedPrompts.addEventListener("click", (event) => {
      const button = event.target.closest("[data-prompt]");
      if (button) sendChat(button.dataset.prompt);
    });

    refs.agentForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const message = refs.agentInput.value.trim();
      if (message) sendChat(message);
    });

    refs.agentInput.addEventListener("input", () => {
      autoGrowInput();
      updateSendButton();
    });

    refs.agentInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        refs.agentForm.requestSubmit();
      }
    });

    refs.agentMessages.addEventListener("click", (event) => {
      const promptButton = event.target.closest("[data-chat-prompt]");
      const openOrdersButton = event.target.closest("[data-chat-open-orders]");
      const detailsButton = event.target.closest("[data-chat-product]");
      const approveButton = event.target.closest("[data-plan-approve]");
      const serviceButton = event.target.closest("[data-service-prompt]");
      const insightsButton = event.target.closest("[data-open-insights]");
      if (promptButton) sendChat(promptButton.dataset.chatPrompt);
      if (openOrdersButton) openOrders();
      if (detailsButton) openProductModal(detailsButton.dataset.chatProduct);
      if (approveButton) approveShoppingPlan(approveButton);
      if (serviceButton) sendChat(serviceButton.dataset.servicePrompt);
      if (insightsButton) openInsights();
    });
    refs.agentMessages.addEventListener("change", (event) => {
      const input = event.target.closest("[data-ticket-evidence]");
      if (input?.files?.[0]) uploadTicketEvidence(input.dataset.ticketEvidence, input.files[0]);
    });

    refs.resetDemoButton.addEventListener("click", resetDemo);
    refs.openOrdersButton.addEventListener("click", openOrders);
    refs.ordersLayer.addEventListener("click", (event) => {
      if (event.target.closest("[data-close-orders]")) closeOrders();
    });

    refs.orderTabs.addEventListener("click", (event) => {
      const button = event.target.closest("[data-order-filter]");
      if (!button) return;
      state.orderFilter = button.dataset.orderFilter || "all";
      refs.orderTabs.querySelectorAll("[data-order-filter]").forEach((tab) => {
        const active = tab === button;
        tab.classList.toggle("active", active);
        tab.setAttribute("aria-selected", String(active));
      });
      renderOrders();
    });

    refs.ordersList.addEventListener("click", (event) => {
      const action = event.target.closest("[data-order-action]");
      if (!action) return;
      const order = state.orders.find((item) => item.id === action.dataset.orderId);
      if (!order) return;
      const firstItem = order.items?.[0];
      closeOrders();
      if (action.dataset.orderAction === "track") {
        openAgent();
        sendChat(`Track order ${order.id}`);
      } else if (action.dataset.orderAction === "cancel") {
        openAgent();
        sendChat(`Cancel order ${order.id}`);
      } else if (action.dataset.orderAction === "reorder" && firstItem) {
        openAgent();
        sendChat(`Place an order for ${firstItem.name}`);
      } else if (action.dataset.orderAction === "return" && firstItem) {
        openAgent(true);
        prefillAgent(`Return ${firstItem.name} from order ${order.id}`);
      } else if (action.dataset.orderAction === "exchange" && firstItem) {
        openAgent(true);
        prefillAgent(`Exchange ${firstItem.name} from order ${order.id}`);
      } else if (action.dataset.orderAction === "service") {
        const requestId = action.dataset.requestId || "";
        openAgent(true);
        prefillAgent(`Track service request ${requestId} for order ${order.id}`.trim());
      } else if (action.dataset.orderAction === "ask") {
        openAgent();
        prefillAgent(`Tell me about order ${order.id}`);
      }
    });

    refs.askAboutOrdersButton.addEventListener("click", () => {
      closeOrders();
      openAgent(true);
      prefillAgent("Show me my recent orders");
    });

    refs.productModalLayer.addEventListener("click", (event) => {
      if (event.target.closest("[data-close-product]")) closeProductModal();
      const orderButton = event.target.closest("[data-modal-order]");
      if (orderButton) {
        const product = findProduct(orderButton.dataset.modalOrder);
        closeProductModal();
        if (product) orderProductWithAgent(product, false);
      }
      const cartButton = event.target.closest("[data-modal-cart]");
      if (cartButton) addToCart(cartButton.dataset.modalCart);
      const reviewsButton = event.target.closest("[data-modal-reviews]");
      if (reviewsButton) {
        const product = findProduct(reviewsButton.dataset.modalReviews);
        closeProductModal();
        if (product) { openAgent(true); sendChat(`Summarize verified reviews for ${product.name}`); }
      }
    });

    refs.openCartButton.addEventListener("click", openCart);
    refs.cartLayer.addEventListener("click", (event) => {
      if (event.target.closest("[data-close-cart]")) closeCart();
      const control = event.target.closest("[data-cart-action]");
      if (control) updateCartItem(control.dataset.productId, control.dataset.cartAction);
    });
    refs.checkoutWithAgentButton.addEventListener("click", () => {
      if (!state.cart.items.length) return;
      closeCart(); openAgent(true); prefillAgent("Checkout my cart");
    });
    refs.accountButton.addEventListener("click", openAccount);
    refs.closeAccountButton.addEventListener("click", closeAccount);
    refs.accountLayer.addEventListener("click", (event) => { if (event.target === refs.accountLayer) closeAccount(); });
    refs.logoutButton.addEventListener("click", logout);
    document.querySelectorAll("[data-auth-tab]").forEach((button) => button.addEventListener("click", () => setAuthMode(button.dataset.authTab)));
    refs.authForm.addEventListener("submit", submitAuth);
    refs.forgotPasswordButton.addEventListener("click", forgotPassword);
    refs.openInsightsButton.addEventListener("click", openInsights);
    refs.closeInsightsButton.addEventListener("click", closeInsights);
    refs.insightsLayer.addEventListener("click", (event) => { if (event.target === refs.insightsLayer) closeInsights(); });
    refs.refreshTracesButton.addEventListener("click", loadInsights);
    refs.traceList.addEventListener("click", (event) => {
      const replay = event.target.closest("[data-replay-trace]");
      if (replay) replayTrace(replay.dataset.replayTrace, replay.dataset.replayPrompt || "");
    });
    refs.preferencesForm.addEventListener("submit", savePreferences);
    refs.clearPreferencesButton.addEventListener("click", clearPreferences);
    refs.proactiveBanner.addEventListener("click", () => { openAgent(true); sendChat("Do any of my orders need proactive assistance?"); });

    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (!refs.productModalLayer.hidden) closeProductModal();
      else if (!refs.ordersLayer.hidden) closeOrders();
      else if (!refs.cartLayer.hidden) closeCart();
      else if (!refs.accountLayer.hidden) closeAccount();
      else if (!refs.insightsLayer.hidden) closeInsights();
      else if (refs.agentPanel.classList.contains("mobile-open")) closeAgent();
    });

    window.addEventListener("resize", () => {
      if (window.innerWidth > 980) {
        refs.agentPanel.classList.remove("mobile-open");
        refs.mobileAgentBackdrop.hidden = true;
        syncBodyLayerState();
      }
    });
  }

  async function loadConfig() {
    try {
      const config = await apiFetch("/api/config");
      state.config = config?.config || config || {};
      applyConfig();
    } catch (error) {
      setAgentMode("offline");
      showToast("Could not load demo configuration", error.message, "error");
    }
  }

  function applyConfig() {
    const config = state.config;
    const user = config.user || {};
    const firstName = user.first_name || String(user.name || "Aarav").split(" ")[0];
    refs.headerUserName.textContent = firstName;
    refs.welcomeUserName.textContent = firstName;
    refs.drawerUserName.textContent = user.name || firstName;
    refs.heroProductCount.textContent = config.product_count || state.products.length || 26;
    if (Number.isFinite(config.order_count)) refs.ordersCount.textContent = config.order_count;
    setAgentMode(config.agent_mode || (config.api_key_configured ? "remote" : "local"), config.model);

    if (Array.isArray(config.categories) && config.categories.length) {
      renderCategories(config.categories);
    }
  }

  async function loadProducts(options = {}) {
    if (!options.quiet) {
      refs.productGrid.setAttribute("aria-busy", "true");
    }
    try {
      const payload = await apiFetch("/api/products?limit=26");
      state.products = Array.isArray(payload) ? payload : (payload.products || []);
      refs.heroProductCount.textContent = state.products.length;
      refs.heroDealCount.textContent = `${state.products.filter((product) => Number(product.discount) >= 15).length}+`;
      const categories = [...new Set(state.products.map((product) => product.category).filter(Boolean))];
      renderCategories(state.config.categories || categories);
      renderProducts();
    } catch (error) {
      if (!options.quiet) renderCatalogError(error.message);
    } finally {
      refs.productGrid.setAttribute("aria-busy", "false");
    }
  }

  async function loadOrders(options = {}) {
    try {
      const payload = await apiFetch("/api/orders");
      state.orders = Array.isArray(payload) ? payload : (payload.orders || []);
      refs.ordersCount.textContent = state.orders.length;
      if (!refs.ordersLayer.hidden || !options.quiet) renderOrders();
    } catch (error) {
      if (!options.quiet) {
        refs.ordersList.innerHTML = `<div class="empty-orders"><span>!</span><h3>Orders are unavailable</h3><p>${escapeHtml(error.message)}</p></div>`;
      }
    }
  }

  function renderCategories(categories) {
    const ordered = Array.from(new Set(["All", ...(categories || [])]));
    if (!ordered.includes(state.category)) state.category = "All";
    refs.categoryPills.innerHTML = ordered.map((category) => {
      const active = category === state.category;
      const icon = CATEGORY_ICONS[category] || "\u25CF";
      const label = category === "All" ? "All products" : category;
      return `<button class="category-pill${active ? " active" : ""}" type="button" data-category="${escapeHtml(category)}" aria-pressed="${active}"><span>${icon}</span> ${escapeHtml(label)}</button>`;
    }).join("");
  }

  function updateCategorySelection() {
    refs.categoryPills.querySelectorAll("[data-category]").forEach((button) => {
      const active = button.dataset.category === state.category;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function renderProducts() {
    const query = normalizeText(state.query);
    let products = state.products.map((product, index) => ({ product, index })).filter(({ product }) => {
      if (state.category !== "All" && product.category !== state.category) return false;
      if (state.maxPrice && Number(product.price) > state.maxPrice) return false;
      if (!query) return true;
      const haystack = normalizeText([
        product.name, product.brand, product.category, product.short_spec,
        ...(Array.isArray(product.specs) ? product.specs : []),
      ].join(" "));
      return query.split(" ").every((token) => haystack.includes(token));
    });

    products.sort((a, b) => {
      if (state.sort === "price-low") return Number(a.product.price) - Number(b.product.price);
      if (state.sort === "price-high") return Number(b.product.price) - Number(a.product.price);
      if (state.sort === "discount") return Number(b.product.discount) - Number(a.product.discount);
      if (state.sort === "rating") return Number(b.product.rating) - Number(a.product.rating);
      return a.index - b.index;
    });

    updateFilterUI(products.length);
    if (!products.length) {
      refs.productGrid.innerHTML = `
        <div class="empty-catalog">
          <div><span>\u{1F50E}</span><h3>No products found</h3><p>Try a different search, category, or price range.</p><button type="button" data-clear-empty>Clear all filters</button></div>
        </div>`;
      refs.productGrid.querySelector("[data-clear-empty]").addEventListener("click", () => clearAllFilters());
      return;
    }

    refs.productGrid.innerHTML = products.map(({ product }) => productCardHTML(product)).join("");
  }

  function productCardHTML(product) {
    const stock = availableStock(product);
    const stockClass = stock <= 0 ? "out-of-stock" : stock <= 5 ? "low-stock" : "";
    const stockText = stock <= 0 ? "Out of stock" : stock <= 5 ? `${stock} left` : "In stock";
    const delivery = cleanDisplayText(product.delivery || "Free delivery in 2-4 days");
    return `
      <article class="product-card" data-product-id="${escapeHtml(product.id)}">
        <div class="product-media theme-${safeTheme(product.theme)}">
          <span class="product-badge">${escapeHtml(product.badge || `${product.discount}% off`)}</span>
          <span class="stock-chip ${stockClass}">${escapeHtml(stockText)}</span>
          <span class="product-icon" aria-hidden="true">${escapeHtml(productIcon(product))}</span>
        </div>
        <div class="product-content">
          <span class="product-category">${escapeHtml(product.brand || product.category)}</span>
          <h3 class="product-name">${escapeHtml(product.name)}</h3>
          <p class="product-spec">${escapeHtml(cleanDisplayText(product.short_spec || ""))}</p>
          <div class="rating-row"><span class="rating-pill"><span>&#9733;</span> ${numberOr(product.rating, "--")}</span><span>${formatCount(product.reviews)} reviews</span></div>
          <div class="price-row"><strong class="current-price">${formatCurrency(product.price)}</strong><span class="mrp">${formatCurrency(product.mrp)}</span><span class="discount">${numberOr(product.discount, 0)}% off</span></div>
          <span class="delivery-note"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h11v10H3V6Zm11 4h4l3 3v3h-7v-6ZM7 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm11 0a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z"/></svg>${escapeHtml(delivery)}</span>
          <div class="product-actions">
            <button class="order-agent-button" type="button" data-order-product="${escapeHtml(product.id)}" ${stock <= 0 ? "disabled" : ""}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 9.8 8.8 4 11l5.8 2.2L12 19l2.2-5.8L20 11l-5.8-2.2L12 3Z"/></svg>
              ${stock <= 0 ? "Unavailable" : "Order via agent"}
            </button>
            <button class="add-cart-button" type="button" data-add-cart="${escapeHtml(product.id)}" ${stock <= 0 ? "disabled" : ""}>Add to cart</button>
            <button class="details-button" type="button" data-product-details="${escapeHtml(product.id)}">Details</button>
          </div>
        </div>
      </article>`;
  }

  function updateFilterUI(count) {
    const hasFilters = Boolean(state.query || state.maxPrice || state.category !== "All" || state.sort !== "featured");
    refs.clearFilters.hidden = !hasFilters;
    refs.searchClear.hidden = !state.query;
    const descriptor = state.category === "All" ? "product" : state.category.toLowerCase();
    refs.resultsSummary.textContent = `${count} ${descriptor}${count === 1 ? "" : "s"}${state.query ? ` matching “${state.query}”` : ""}`;
  }

  function setSearch(value) {
    state.query = value.trim();
    refs.searchClear.hidden = !state.query;
    renderProducts();
  }

  function clearAllFilters(shouldRender = true) {
    state.category = "All";
    state.query = "";
    state.maxPrice = null;
    state.sort = "featured";
    refs.globalSearch.value = "";
    refs.priceFilter.value = "";
    refs.sortProducts.value = "featured";
    updateCategorySelection();
    if (shouldRender) renderProducts();
  }

  function renderCatalogError(message) {
    refs.resultsSummary.textContent = "The catalog could not be loaded";
    refs.productGrid.innerHTML = `
      <div class="catalog-error">
        <div><span>\u26A0</span><h3>Could not load products</h3><p>${escapeHtml(message)}</p><button type="button" data-retry-products>Try again</button></div>
      </div>`;
  }

  function openProductModal(productId) {
    const product = findProduct(productId);
    if (!product) return;
    state.lastFocus = document.activeElement;
    const stock = availableStock(product);
    refs.productModalContent.innerHTML = `
      <div class="product-modal-layout">
        <div class="product-modal-media theme-${safeTheme(product.theme)}">
          <span class="product-badge">${escapeHtml(product.badge || `${product.discount}% off`)}</span>
          <span class="product-icon" aria-hidden="true">${escapeHtml(productIcon(product))}</span>
        </div>
        <div class="product-modal-body">
          <span class="eyebrow">${escapeHtml(product.category)} &middot; ${escapeHtml(product.brand)}</span>
          <h2 id="productModalTitle">${escapeHtml(product.name)}</h2>
          <p>${escapeHtml(cleanDisplayText(product.short_spec || ""))}</p>
          <div class="rating-row"><span class="rating-pill"><span>&#9733;</span> ${numberOr(product.rating, "--")}</span><span>${formatCount(product.reviews)} verified demo reviews</span></div>
          <div class="modal-price-row"><strong class="current-price">${formatCurrency(product.price)}</strong><span class="mrp">${formatCurrency(product.mrp)}</span><span class="discount">Save ${formatCurrency(Number(product.mrp || 0) - Number(product.price || 0))}</span></div>
          <div class="modal-specs">${(product.specs || []).map((spec) => `<span>${escapeHtml(cleanDisplayText(spec))}</span>`).join("")}</div>
          <button class="modal-agent-button" type="button" data-modal-order="${escapeHtml(product.id)}" ${stock <= 0 ? "disabled" : ""}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 9.8 8.8 4 11l5.8 2.2L12 19l2.2-5.8L20 11l-5.8-2.2L12 3Z"/></svg>
            ${stock <= 0 ? "Currently out of stock" : "Order this with Volt"}
          </button>
          <div class="modal-secondary-actions">
            <button type="button" data-modal-cart="${escapeHtml(product.id)}" ${stock <= 0 ? "disabled" : ""}>Add to cart</button>
            <button type="button" data-modal-reviews="${escapeHtml(product.id)}">AI review summary</button>
          </div>
        </div>
      </div>`;
    refs.productModalLayer.hidden = false;
    syncBodyLayerState();
    requestAnimationFrame(() => refs.productModal.focus());
  }

  function closeProductModal() {
    refs.productModalLayer.hidden = true;
    syncBodyLayerState();
    restoreFocus();
  }

  function openAuth() {
    closeAccount();
    refs.authLayer.hidden = false;
    refs.agentInput.disabled = true;
    refs.authError.textContent = "";
    syncBodyLayerState();
    setTimeout(() => refs.authEmail.focus(), 50);
  }

  function setAuthMode(mode) {
    state.authMode = mode === "register" ? "register" : "login";
    const registering = state.authMode === "register";
    document.querySelectorAll("[data-auth-tab]").forEach((button) => button.classList.toggle("active", button.dataset.authTab === state.authMode));
    document.querySelectorAll(".register-field").forEach((field) => { field.hidden = !registering; });
    refs.authName.required = registering;
    refs.authPhone.required = registering;
    refs.authPassword.autocomplete = registering ? "new-password" : "current-password";
    refs.authTitle.textContent = registering ? "Create your account" : "Welcome back";
    refs.authSubtitle.textContent = registering ? "Your cart, orders and support tickets stay private to this account." : "Sign in to keep carts, orders and support requests separate.";
    refs.authSubmit.textContent = registering ? "Create account" : "Sign in";
    refs.forgotPasswordButton.hidden = registering;
    refs.authError.textContent = "";
  }

  async function submitAuth(event) {
    event.preventDefault();
    refs.authError.textContent = "";
    refs.authSubmit.disabled = true;
    const body = { email: refs.authEmail.value.trim(), password: refs.authPassword.value };
    if (state.authMode === "register") Object.assign(body, { name: refs.authName.value.trim(), phone: refs.authPhone.value.trim() });
    try {
      const payload = await apiFetch(`/api/auth/${state.authMode}`, { method: "POST", body: JSON.stringify(body) });
      await completeSignIn(payload.user);
      showToast(state.authMode === "register" ? "Account created" : "Signed in", `Welcome, ${payload.user.name}.`, "success");
    } catch (error) {
      refs.authError.textContent = error.message;
    } finally {
      refs.authSubmit.disabled = false;
    }
  }

  async function forgotPassword() {
    const email = refs.authEmail.value.trim();
    if (!email) { refs.authError.textContent = "Enter your email first."; return; }
    try {
      const payload = await apiFetch("/api/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) });
      refs.authError.textContent = "";
      showToast("Mock reset recorded", payload.message, "info");
    } catch (error) { refs.authError.textContent = error.message; }
  }

  async function completeSignIn(user) {
    state.user = user;
    refs.authLayer.hidden = true;
    refs.agentInput.disabled = false;
    refs.accountName.textContent = String(user.name || "Account").split(" ")[0];
    await Promise.allSettled([loadConfig(), loadOrders({ quiet: true }), loadCart(), loadPreferences(), loadProactiveAssistance()]);
    syncBodyLayerState();
    updateSendButton();
  }

  async function logout() {
    try { await apiFetch("/api/auth/logout", { method: "POST", body: "{}" }); } catch (_) { /* Clear the local UI even if logout fails. */ }
    state.user = null;
    state.orders = [];
    state.cart = { items: [], item_count: 0, total: 0 };
    refs.ordersCount.textContent = "0";
    refs.cartCount.textContent = "0";
    closeAccount();
    clearConversationUI();
    setAuthMode("login");
    openAuth();
  }

  async function openAccount() {
    if (!state.user) { openAuth(); return; }
    state.lastFocus = document.activeElement;
    refs.accountDetails.innerHTML = `<dl class="account-data"><dt>Name</dt><dd>${escapeHtml(state.user.name)}</dd><dt>Email</dt><dd>${escapeHtml(state.user.email)}</dd><dt>Phone</dt><dd>${escapeHtml(state.user.phone)}</dd><dt>Local user ID</dt><dd>${escapeHtml(state.user.id)}</dd></dl>`;
    refs.accountLayer.hidden = false;
    await loadPreferences();
    syncBodyLayerState();
  }

  function closeAccount() {
    refs.accountLayer.hidden = true;
    syncBodyLayerState();
  }

  async function loadPreferences() {
    if (!state.user) return;
    try {
      const payload = await apiFetch("/api/preferences");
      state.preferences = payload.preferences || {};
      refs.preferenceEnabled.checked = state.preferences.enabled !== false;
      refs.preferenceBudget.value = state.preferences.budget || "";
      refs.preferenceBrands.value = toArray(state.preferences.favorite_brands).join(", ");
      refs.preferenceExcluded.value = toArray(state.preferences.excluded_brands).join(", ");
      refs.preferenceLocation.value = state.preferences.delivery_location || "";
      refs.preferenceUrgency.value = state.preferences.delivery_urgency || "";
    } catch (error) { showToast("Memory unavailable", error.message, "error"); }
  }

  async function savePreferences(event) {
    event.preventDefault();
    const csvValues = (value) => String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
    try {
      const payload = await apiFetch("/api/preferences", { method: "POST", body: JSON.stringify({
        enabled: refs.preferenceEnabled.checked,
        budget: refs.preferenceBudget.value ? Number(refs.preferenceBudget.value) : null,
        favorite_brands: csvValues(refs.preferenceBrands.value),
        excluded_brands: csvValues(refs.preferenceExcluded.value),
        delivery_location: refs.preferenceLocation.value.trim(),
        delivery_urgency: refs.preferenceUrgency.value.trim(),
      }) });
      state.preferences = payload.preferences;
      showToast("Agent memory saved", "Volt can now ground recommendations in these preferences.", "success");
    } catch (error) { showToast("Could not save memory", error.message, "error"); }
  }

  async function clearPreferences() {
    try {
      const payload = await apiFetch("/api/preferences", { method: "DELETE" });
      state.preferences = payload.preferences;
      await loadPreferences();
      showToast("Agent memory erased", "Saved shopping preferences were removed.", "info");
    } catch (error) { showToast("Could not erase memory", error.message, "error"); }
  }

  async function loadProactiveAssistance() {
    if (!state.user) return;
    try {
      const payload = await apiFetch("/api/proactive-assistance");
      const item = toArray(payload.assistance)[0];
      refs.proactiveBanner.hidden = !item;
      if (item) refs.proactiveBanner.innerHTML = `<strong>Delivery update for ${escapeHtml(item.order_id)}</strong><span>${escapeHtml(item.message || item.reason || "A shipment may be delayed.")}</span><button type="button">Ask Volt for options</button>`;
    } catch (_) { refs.proactiveBanner.hidden = true; }
  }

  async function loadCart() {
    if (!state.user) return;
    try {
      const payload = await apiFetch("/api/cart");
      state.cart = payload.cart || { items: [], item_count: 0, total: 0 };
      renderCart();
    } catch (error) { showToast("Cart unavailable", error.message, "error"); }
  }

  async function addToCart(productId) {
    if (!state.user) { openAuth(); return; }
    const existing = state.cart.items.find((item) => item.id === productId);
    const quantity = Number(existing?.quantity || 0) + 1;
    try {
      const payload = await apiFetch("/api/cart/items", { method: "POST", body: JSON.stringify({ product_id: productId, quantity }) });
      state.cart = payload.cart;
      renderCart();
      showToast("Added to cart", findProduct(productId)?.name || productId, "success");
    } catch (error) { showToast("Could not update cart", error.message, "error"); }
  }

  async function updateCartItem(productId, action) {
    const item = state.cart.items.find((entry) => entry.id === productId);
    if (!item) return;
    try {
      const remove = action === "remove" || (action === "decrease" && item.quantity <= 1);
      const payload = await apiFetch(`/api/cart/items/${encodeURIComponent(productId)}`, remove
        ? { method: "DELETE" }
        : { method: "PATCH", body: JSON.stringify({ quantity: item.quantity + (action === "increase" ? 1 : -1) }) });
      state.cart = payload.cart;
      renderCart();
    } catch (error) { showToast("Could not update cart", error.message, "error"); }
  }

  function renderCart() {
    refs.cartCount.textContent = String(state.cart.item_count || 0);
    refs.cartTotal.textContent = formatCurrency(state.cart.total);
    refs.checkoutWithAgentButton.disabled = !state.cart.items.length;
    refs.cartItems.innerHTML = state.cart.items.length ? state.cart.items.map((item) => `
      <article class="cart-item">
        <span class="cart-item-icon" aria-hidden="true">${escapeHtml(productIcon(item))}</span>
        <span class="cart-item-copy"><strong>${escapeHtml(item.name)}</strong><small>${formatCurrency(item.price)} each &middot; Save ${formatCurrency((item.mrp - item.price) * item.quantity)}</small><b>${formatCurrency(item.line_total)}</b></span>
        <span class="cart-item-controls"><button type="button" data-cart-action="decrease" data-product-id="${escapeHtml(item.id)}" aria-label="Decrease quantity">&minus;</button><strong>${item.quantity}</strong><button type="button" data-cart-action="increase" data-product-id="${escapeHtml(item.id)}" aria-label="Increase quantity">+</button><button type="button" data-cart-action="remove" data-product-id="${escapeHtml(item.id)}" aria-label="Remove item">&times;</button></span>
      </article>`).join("") : `<div class="empty-orders"><span>&#128722;</span><h3>Your cart is empty</h3><p>Add a product, then ask Volt to place the order.</p></div>`;
  }

  function openCart() {
    if (!state.user) { openAuth(); return; }
    state.lastFocus = document.activeElement;
    renderCart();
    refs.cartLayer.hidden = false;
    syncBodyLayerState();
    requestAnimationFrame(() => refs.cartDrawer.focus());
  }

  function closeCart() {
    refs.cartLayer.hidden = true;
    syncBodyLayerState();
  }

  function openOrders() {
    state.lastFocus = document.activeElement;
    refs.ordersLayer.hidden = false;
    renderOrders();
    syncBodyLayerState();
    requestAnimationFrame(() => refs.ordersDrawer.focus());
  }

  function closeOrders() {
    refs.ordersLayer.hidden = true;
    syncBodyLayerState();
    restoreFocus();
  }

  function renderOrders() {
    let orders = [...state.orders];
    if (state.orderFilter === "active") orders = orders.filter((order) => ACTIVE_ORDER_STATUSES.has(order.status));
    if (state.orderFilter === "delivered") orders = orders.filter((order) => order.status === "Delivered");
    if (state.orderFilter === "cancelled") orders = orders.filter((order) => order.status === "Cancelled");
    if (!orders.length) {
      refs.ordersList.innerHTML = `<div class="empty-orders"><span>\u{1F4E6}</span><h3>No ${state.orderFilter === "all" ? "" : escapeHtml(state.orderFilter)} orders</h3><p>Ask Volt to place a demo order from the catalog.</p></div>`;
      return;
    }
    refs.ordersList.innerHTML = orders.map(orderCardHTML).join("");
  }

  function orderCardHTML(order) {
    const items = Array.isArray(order.items) ? order.items : [];
    const firstItem = items[0] || {};
    const isCancelled = order.status === "Cancelled";
    const canCancel = Boolean(order.cancellable) && !isCancelled;
    const isDelivered = order.status === "Delivered";
    const serviceRequests = Array.isArray(order.service_requests) ? order.service_requests : [];
    const latestService = [...serviceRequests].sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")))[0] || null;
    const serviceOpen = latestService && !["Completed", "Rejected", "Cancelled", "Refunded", "Exchanged"].includes(latestService.status);
    return `
      <article class="order-card">
        <header class="order-card-header">
          <span class="order-card-id"><strong>${escapeHtml(order.id || "Order")}</strong><small>Ordered ${formatDate(order.created_at, { dateStyle: "medium" })}</small></span>
          <span class="order-status-pill ${statusClass(order.status)}">${escapeHtml(order.status || "Unknown")}</span>
        </header>
        <div class="order-card-body">
          <div class="order-item-row">
            <span class="order-item-icon" aria-hidden="true">${escapeHtml(itemIcon(firstItem))}</span>
            <span class="order-item-copy"><strong>${escapeHtml(firstItem.name || "Order item")}</strong><small>${escapeHtml(firstItem.brand || "")} &middot; Qty ${numberOr(firstItem.quantity, 1)}</small></span>
            <strong class="order-item-price">${formatCurrency(firstItem.line_total || firstItem.unit_price || order.total)}</strong>
          </div>
          ${items.length > 1 ? `<p class="more-items-note">+${items.length - 1} more item${items.length > 2 ? "s" : ""}</p>` : ""}
          ${isCancelled ? `<div class="order-cancelled-note"><span>&#10005;</span><span>This order was cancelled. Reserved stock has been released.</span></div>` : orderProgressHTML(order.status)}
          ${latestService ? orderServiceNoteHTML(latestService) : ""}
          <div class="order-summary-row">
            <span class="order-eta"><span>${isDelivered ? "Delivered on" : isCancelled ? "Updated" : "Estimated delivery"}</span><strong>${formatDate(isDelivered ? order.updated_at : isCancelled ? order.updated_at : order.estimated_delivery, { dateStyle: "medium" })}</strong></span>
            <span class="order-total"><span>Order total</span><strong>${formatCurrency(order.total)}</strong></span>
          </div>
        </div>
        <footer class="order-card-actions">
          ${!isCancelled && !isDelivered ? `<button class="primary" type="button" data-order-action="track" data-order-id="${escapeHtml(order.id)}">Track with Volt</button>` : ""}
          ${canCancel ? `<button class="danger" type="button" data-order-action="cancel" data-order-id="${escapeHtml(order.id)}">Cancel order</button>` : ""}
          ${isDelivered || isCancelled ? `<button type="button" data-order-action="reorder" data-order-id="${escapeHtml(order.id)}">${isDelivered ? "Reorder" : "Order again"}</button>` : ""}
          ${isDelivered && order.return_eligible && !serviceOpen ? `<button type="button" data-order-action="return" data-order-id="${escapeHtml(order.id)}">Return item</button>` : ""}
          ${isDelivered && order.exchange_eligible && !serviceOpen ? `<button type="button" data-order-action="exchange" data-order-id="${escapeHtml(order.id)}">Exchange item</button>` : ""}
          ${latestService ? `<button type="button" data-order-action="service" data-order-id="${escapeHtml(order.id)}" data-request-id="${escapeHtml(latestService.id || "")}">Track ${escapeHtml(String(latestService.type || "service").toLowerCase())}</button>` : ""}
          <button type="button" data-order-action="ask" data-order-id="${escapeHtml(order.id)}">Ask a question</button>
        </footer>
      </article>`;
  }

  function orderServiceNoteHTML(request) {
    const type = request.type || "Service";
    const detail = type === "Exchange"
      ? (request.replacement_eta ? `Replacement expected ${formatDate(request.replacement_eta, { dateStyle: "medium" })}` : "Replacement is being arranged")
      : (request.refund_amount ? `${formatCurrency(request.refund_amount)} refund requested` : "Return is being arranged");
    return `
      <div class="service-request-note">
        <span class="service-request-icon" aria-hidden="true">${type === "Exchange" ? "&#8644;" : "&#8630;"}</span>
        <span><strong>${escapeHtml(type)} ${escapeHtml(request.status || "requested")}</strong><small>${escapeHtml(request.id || "")} &middot; ${escapeHtml(detail)}</small></span>
      </div>`;
  }

  function orderProgressHTML(status) {
    let currentIndex = STATUS_STEPS.indexOf(status);
    if (status === "Processing") currentIndex = 0;
    if (status === "Out for delivery") currentIndex = 2;
    if (currentIndex < 0) currentIndex = 0;
    return `<div class="order-progress" aria-label="Order progress">${STATUS_STEPS.map((step, index) => {
      const cssClass = index < currentIndex ? "complete" : index === currentIndex ? "current" : "";
      const label = step === "Shipped" && status === "Out for delivery" ? "Out for delivery" : step;
      return `<span class="progress-step ${cssClass}"><i class="progress-dot"></i><span>${escapeHtml(label)}</span></span>`;
    }).join("")}</div>`;
  }

  function openAgent(focus = false) {
    refs.agentPanel.classList.remove("is-collapsed");
    refs.storeLayout.classList.remove("agent-collapsed");
    if (window.innerWidth <= 980) {
      refs.agentPanel.classList.add("mobile-open");
      refs.mobileAgentBackdrop.hidden = false;
      syncBodyLayerState();
    }
    if (focus) setTimeout(() => refs.agentInput.focus(), 120);
    scrollChatToBottom();
  }

  function closeAgent() {
    refs.agentPanel.classList.remove("mobile-open");
    refs.mobileAgentBackdrop.hidden = true;
    syncBodyLayerState();
  }

  function prefillAgent(message) {
    refs.agentInput.value = message;
    autoGrowInput();
    updateSendButton();
    refs.agentInput.focus();
  }

  function orderProductWithAgent(product, autoSend = false) {
    openAgent(true);
    const prompt = `Place an order for 1 x ${product.name}`;
    if (autoSend) sendChat(prompt);
    else prefillAgent(prompt);
  }

  async function sendChat(rawMessage) {
    const message = String(rawMessage || "").trim();
    if (!message || state.chatBusy) return null;
    const messageId = createMessageId();
    let responseData = null;
    state.chatBusy = true;
    refs.agentInput.value = "";
    autoGrowInput();
    updateSendButton();
    refs.suggestedPrompts.hidden = true;
    addUserMessage(message);
    const typing = addTypingMessage(message);
    openAgent();

    try {
      const data = await apiFetch("/api/chat", {
        method: "POST",
        body: JSON.stringify({ message, session_id: state.sessionId, message_id: messageId }),
        timeout: 600000,
      });
      responseData = data;
      typing.remove();
      addAssistantMessage(data || {});
      setAgentMode(data.mode || state.config.agent_mode || "local", data.model || state.config.model);
      const actions = Array.isArray(data.actions) ? data.actions : [];
      if (actions.some(isMutatingAction)) {
        await Promise.all([loadProducts({ quiet: true }), loadOrders({ quiet: true }), loadCart()]);
        const successfulAction = actions.find((action) => isMutatingAction(action) && action.result?.ok !== false);
        if (successfulAction?.tool === "place_order") {
          const plan = successfulAction.result?.shopping_plan;
          if (plan) showToast("Shopping plan ready", `${plan.id || "Plan"} needs your approval before ordering.`, "info");
          else showToast("Order placed", successfulAction.result?.order?.id || "Your new order is confirmed.", "success");
        }
        if (successfulAction?.tool === "checkout_cart") {
          const plan = successfulAction.result?.shopping_plan;
          if (plan) showToast("Cart plan ready", `${plan.id} needs approval before ordering.`, "info");
          else showToast("Cart ordered", successfulAction.result?.order?.id || "The cart was checked out.", "success");
        }
        if (successfulAction?.tool === "cancel_order") showToast("Order cancelled", successfulAction.result?.order?.id || "The order was cancelled.", "info");
        if (successfulAction?.tool === "approve_purchase") showToast("Purchase approved", successfulAction.result?.order?.id || "Your shopping plan was approved and ordered.", "success");
        if (successfulAction?.tool === "create_return_request") {
          const request = successfulAction.result?.return_request || successfulAction.result?.request || {};
          showToast(`${request.type || "Return"} requested`, request.id || "Your service request was created.", "success");
        }
        if (successfulAction?.tool === "create_support_ticket") showToast("Support ticket created", successfulAction.result?.ticket?.id || "Your issue was recorded.", "success");
        if (successfulAction?.tool === "escalate_support_ticket") showToast("Human handoff simulated", successfulAction.result?.ticket?.assigned_to || "The ticket was escalated.", "info");
      }
    } catch (error) {
      typing.remove();
      addErrorMessage(error.message || "The agent could not complete that request.");
      showToast("Agent request failed", error.message, "error");
    } finally {
      state.chatBusy = false;
      refs.agentInput.disabled = false;
      updateSendButton();
      refs.agentInput.focus();
      scrollChatToBottom();
    }
    return responseData;
  }

  async function approveShoppingPlan(button) {
    if (state.chatBusy || button.disabled) return;
    let approvalMessage = "";
    try {
      approvalMessage = decodeURIComponent(String(button.dataset.planApprove || "")).trim();
    } catch (_) {
      approvalMessage = String(button.dataset.planApprove || "").trim();
    }
    if (!approvalMessage) {
      showToast("Approval unavailable", "This plan does not include an approval message.", "error");
      return;
    }
    const planCard = button.closest(".chat-plan-card");
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = "Approving...";
    planCard?.setAttribute("aria-busy", "true");
    const response = await sendChat(approvalMessage);
    const approved = Boolean(
      response?.actions?.some((action) => action.tool === "approve_purchase" && action.result?.ok !== false)
      || response?.entities?.order
    );
    planCard?.removeAttribute("aria-busy");
    if (approved) {
      button.textContent = "Approved";
      button.classList.add("approved");
    } else {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  }

  function addUserMessage(message) {
    const article = document.createElement("article");
    article.className = "chat-message user-message";
    article.innerHTML = `<div class="message-stack"><div class="message-bubble"><p>${escapeHtml(message)}</p></div><span class="message-time">${currentTime()}</span></div>`;
    refs.agentMessages.appendChild(article);
    scrollChatToBottom();
  }

  function addTypingMessage(message) {
    const lower = message.toLowerCase();
    let label = lower.includes("cancel") ? "Finding the order..." : lower.includes("track") || lower.includes("status") ? "Checking the order..." : lower.includes("order") || lower.includes("buy") ? "Checking stock..." : "Searching the catalog...";
    const article = document.createElement("article");
    article.className = "chat-message assistant-message typing-message";
    article.innerHTML = `<div class="message-avatar" aria-hidden="true"><span>&#10022;</span></div><div class="message-stack"><div class="message-bubble"><div class="typing-state"><span class="typing-dots"><i></i><i></i><i></i></span><span class="typing-label">${escapeHtml(label)}</span></div></div></div>`;
    refs.agentMessages.appendChild(article);
    scrollChatToBottom();
    const labels = lower.includes("order") ? [label, "Verifying live data...", "Completing the action..."] : [label, "Reading live store data...", "Preparing the answer..."];
    let index = 0;
    const timer = window.setInterval(() => {
      if (!article.isConnected) {
        window.clearInterval(timer);
        return;
      }
      index = Math.min(index + 1, labels.length - 1);
      article.querySelector(".typing-label").textContent = labels[index];
    }, 1300);
    article._typingTimer = timer;
    const originalRemove = article.remove.bind(article);
    article.remove = () => {
      window.clearInterval(timer);
      originalRemove();
    };
    return article;
  }

  function addAssistantMessage(data) {
    const article = document.createElement("article");
    article.className = "chat-message assistant-message";
    const actions = Array.isArray(data.actions) ? data.actions : [];
    const entityHTML = renderChatEntities(data.entities || {}, actions);
    const actionLogHTML = actions.length ? renderActionLog(actions) : "";
    const traceHTML = data.trace ? renderInlineTrace(data.trace) : "";
    const warningHTML = data.warning ? `<div class="agent-warning" role="status">${escapeHtml(data.warning)}</div>` : "";
    const mode = String(data.mode || state.config.agent_mode || "local").toLowerCase();
    const model = data.model || state.config.model || "";
    const modeLabel = mode === "remote" ? (model || "GPT agent") : "Local demo agent";
    article.innerHTML = `
      <div class="message-avatar" aria-hidden="true"><span>&#10022;</span></div>
      <div class="message-stack">
        <div class="message-bubble"><p>${formatMessageText(data.message || "Done.")}</p></div>
        ${warningHTML}
        ${entityHTML}
        ${actionLogHTML}
        ${traceHTML}
        <div class="message-meta"><span>${currentTime()}</span><span class="mode-tag ${mode === "remote" ? "" : "local"}">${escapeHtml(modeLabel)}</span></div>
      </div>`;
    refs.agentMessages.appendChild(article);
    scrollChatToBottom();
  }

  function renderInlineTrace(trace) {
    const tools = toArray(trace.actions).map((action) => humanToolName(action.tool)).join(" → ") || "No tool call";
    return `<details class="inline-trace"><summary>Agent trace &middot; ${escapeHtml(trace.correlation_id)}</summary><div class="inline-trace-grid"><span>Intent<strong>${escapeHtml(trace.intent)}</strong></span><span>Confidence<strong>${numberOr(trace.confidence, 0).toFixed(2)}${trace.clarification ? " / clarification" : ""}</strong></span><span>Runtime<strong>${escapeHtml(trace.mode)} &middot; ${escapeHtml(trace.model)}</strong></span><span>Usage<strong>${numberOr(trace.total_tokens, 0)} tokens &middot; ${numberOr(trace.latency_ms, 0)} ms</strong></span></div><p><strong>Tools:</strong> ${escapeHtml(tools)}</p><p><strong>Guardrails:</strong> ${escapeHtml(toArray(trace.guardrails).map((item) => `${item.check}: ${item.decision}`).join(", "))}</p>${trace.fallback_reason ? `<p><strong>Fallback reason:</strong> ${escapeHtml(trace.fallback_reason)}</p>` : ""}<button type="button" data-open-insights>Open trace viewer</button></details>`;
  }

  function addErrorMessage(message) {
    const article = document.createElement("article");
    article.className = "chat-message assistant-message error-message";
    article.innerHTML = `<div class="message-avatar" aria-hidden="true"><span>!</span></div><div class="message-stack"><div class="message-bubble"><p>${escapeHtml(message)} Please try again.</p></div><span class="message-time">${currentTime()}</span></div>`;
    refs.agentMessages.appendChild(article);
  }

  function renderChatEntities(entities, actions) {
    const plans = toArray(entities.shopping_plan).filter(isShoppingPlan);
    const serviceRequests = uniqueById([
      ...toArray(entities.return_request),
      ...toArray(entities.return_requests),
    ].filter(isServiceRequest));
    const orders = uniqueById([
      ...toArray(entities.order),
      ...toArray(entities.orders),
    ].filter(isOrder));
    const products = uniqueById([
      ...toArray(entities.product),
      ...toArray(entities.products),
    ].filter(isProduct));
    const tickets = uniqueById([
      ...toArray(entities.ticket),
      ...toArray(entities.tickets),
    ].filter(isSupportTicket));
    const reviewSummary = entities.review_summary && typeof entities.review_summary === "object" ? entities.review_summary : null;
    const preferences = entities.preferences && typeof entities.preferences === "object" ? entities.preferences : null;
    const cart = entities.cart && typeof entities.cart === "object" ? entities.cart : null;
    const modification = entities.modification && typeof entities.modification === "object" ? entities.modification : null;
    const resolution = entities.resolution && typeof entities.resolution === "object" ? entities.resolution : null;
    const assistance = toArray(entities.assistance);
    const supportDraft = entities.support_draft && typeof entities.support_draft === "object" ? entities.support_draft : null;
    const faqs = toArray(entities.faqs).filter((faq) => faq && faq.question && faq.answer);
    const placed = actions.some((action) =>
      ["place_order", "approve_purchase"].includes(action.tool)
      && action.result?.ok !== false
      && isOrder(action.result?.order)
    );
    const cancelled = actions.some((action) => action.tool === "cancel_order" && action.result?.ok !== false);
    const cards = [];
    if (preferences) cards.push(`<section class="chat-review-card"><h4>Agent memory</h4><p><strong>Budget:</strong> ${preferences.budget ? formatCurrency(preferences.budget) : "Not set"}</p><p><strong>Favourite:</strong> ${escapeHtml(toArray(preferences.favorite_brands).join(", ") || "None")} &middot; <strong>Excluded:</strong> ${escapeHtml(toArray(preferences.excluded_brands).join(", ") || "None")}</p><small>${preferences.enabled === false ? "Memory is disabled" : "Visible and editable from Account"}</small></section>`);
    if (cart) cards.push(`<section class="chat-review-card"><h4>Conversational cart</h4><p>${numberOr(cart.item_count, 0)} item(s) &middot; <strong>${formatCurrency(cart.total)}</strong></p><small>Stock, saved prices and offers are validated at checkout.</small></section>`);
    if (modification) cards.push(`<section class="chat-review-card"><h4>Order modification &middot; ${escapeHtml(modification.status || "Pending")}</h4><p>${escapeHtml(modification.id || "")} &middot; Order ${escapeHtml(modification.order_id || "")}</p><p>${escapeHtml(modification.confirmation_message || "Review the proposed changes before confirming.")}</p></section>`);
    if (resolution) cards.push(`<section class="chat-review-card"><h4>Recommended resolution: ${escapeHtml(resolution.recommended_resolution || "Support")}</h4><p>${escapeHtml(resolution.explanation || "Based on the order state and demo policy.")}</p><small>Policy-grounded recommendation</small></section>`);
    if (assistance.length) cards.push(...assistance.slice(0, 2).map((item) => `<section class="chat-review-card"><h4>Proactive delivery assistance</h4><p><strong>${escapeHtml(item.order_id || "Order")}</strong> &middot; ${escapeHtml(item.message || item.reason || "Delay detected")}</p><button type="button" data-chat-prompt="Create a delivery delay ticket for order ${escapeHtml(item.order_id || "")}">Create ticket</button></section>`));
    if (supportDraft) cards.push(`<section class="chat-review-card"><h4>Support details collected</h4><p>${escapeHtml(supportDraft.subject || supportDraft.category || "Issue")}</p><small>Reply with the exact order ID to validate ownership and create the ticket.</small></section>`);
    if (reviewSummary) cards.push(chatReviewSummaryHTML(reviewSummary));
    if (tickets.length) cards.push(...tickets.slice(0, 3).map(chatTicketHTML));
    if (faqs.length) cards.push(...faqs.slice(0, 2).map(chatFaqHTML));
    if (plans.length) {
      cards.push(...plans.slice(0, 2).map(chatShoppingPlanHTML));
    }
    if (serviceRequests.length) {
      cards.push(...serviceRequests.slice(0, 3).map(chatServiceRequestHTML));
    }
    if (!plans.length && !serviceRequests.length && !tickets.length && !reviewSummary && !faqs.length && orders.length) {
      cards.push(...orders.slice(0, 3).map((order, index) => chatOrderCardHTML(order, { placed: placed && index === 0, cancelled })));
    } else if (!plans.length && !serviceRequests.length && !tickets.length && !reviewSummary && !faqs.length && products.length) {
      cards.push(...products.slice(0, 3).map(chatProductCardHTML));
    }
    return cards.length ? `<div class="entity-cards">${cards.join("")}</div>` : "";
  }

  function chatReviewSummaryHTML(summary) {
    const product = summary.product || {};
    const praises = toArray(summary.common_praises).slice(0, 3).join(", ");
    const tradeoffs = toArray(summary.common_tradeoffs).slice(0, 2).join(", ");
    return `<section class="chat-review-card"><h4>&#9733; Verified review summary</h4><p><strong>${escapeHtml(product.name || "Product")}</strong> &middot; ${numberOr(summary.average_rating, 0)}/5 from ${numberOr(summary.review_count, 0)} seeded reviews</p><p><strong>Customers like:</strong> ${escapeHtml(praises || "No recurring theme yet")}</p><p><strong>Trade-offs:</strong> ${escapeHtml(tradeoffs || "None consistently reported")}</p><small>Grounded only in reviews stored in SQLite.</small></section>`;
  }

  function chatTicketHTML(ticket) {
    return `<section class="chat-ticket-card"><h4>${escapeHtml(ticket.id)} &middot; ${escapeHtml(ticket.status)}</h4><p><strong>${escapeHtml(ticket.subject)}</strong></p><p>${escapeHtml(ticket.category.replace(/_/g, " "))} &middot; ${escapeHtml(ticket.priority)} priority &middot; ${escapeHtml(ticket.assigned_to)}</p><p>${numberOr(ticket.attachments?.length, 0)} evidence file(s)</p><label class="ticket-upload">Attach image evidence<input type="file" accept="image/png,image/jpeg,image/webp" data-ticket-evidence="${escapeHtml(ticket.id)}"></label>${ticket.status !== "Resolved" && ticket.status !== "Escalated" ? `<button type="button" data-chat-prompt="Escalate ticket ${escapeHtml(ticket.id)} to a human agent">Escalate to human</button>` : ""}</section>`;
  }

  async function uploadTicketEvidence(ticketId, file) {
    if (file.size > 1024 * 1024) { showToast("Evidence too large", "Choose an image up to 1 MB.", "error"); return; }
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) { showToast("Unsupported evidence", "Use PNG, JPEG or WebP.", "error"); return; }
    try {
      const dataUrl = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file); });
      const contentBase64 = String(dataUrl).split(",", 2)[1] || "";
      await apiFetch(`/api/support/tickets/${encodeURIComponent(ticketId)}/attachments`, { method: "POST", body: JSON.stringify({ file_name: file.name, mime_type: file.type, content_base64: contentBase64 }) });
      showToast("Evidence attached", `${file.name} was added to ${ticketId}.`, "success");
    } catch (error) { showToast("Could not attach evidence", error.message, "error"); }
  }

  function chatFaqHTML(faq) {
    return `<section class="chat-review-card"><h4>${escapeHtml(faq.question)}</h4><p>${escapeHtml(faq.answer)}</p><small>VoltCart demo policy</small></section>`;
  }

  function chatShoppingPlanHTML(plan) {
    const items = Array.isArray(plan.items) ? plan.items : [];
    const pending = String(plan.status || "").toLowerCase() === "pending";
    const approvalValue = encodeURIComponent(String(plan.approval_message || ""));
    return `
      <section class="chat-plan-card" role="group" aria-label="Shopping plan awaiting approval">
        <header class="plan-header">
          <span class="plan-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M7 3h10l2 4v13H5V7l2-4Zm-2 4h14M9 11a3 3 0 0 0 6 0"/></svg></span>
          <span class="plan-title"><strong>Shopping plan</strong><small>${escapeHtml(plan.id || "")} &middot; ${escapeHtml(plan.mission || "Curated for your request")}</small></span>
          <span class="plan-status ${pending ? "pending" : ""}">${escapeHtml(plan.status || "Pending")}</span>
        </header>
        <div class="plan-items">${items.map((item) => `
          <div class="plan-item">
            <span class="plan-item-icon" aria-hidden="true">${escapeHtml(planItemIcon(item))}</span>
            <span class="plan-item-copy"><strong>${escapeHtml(item.name || "Product")}</strong><small>${escapeHtml(item.need || item.brand || "Selected for this plan")} &middot; Qty ${numberOr(item.quantity, 1)}</small></span>
            <strong class="plan-item-price">${formatCurrency(item.line_total || Number(item.unit_price || 0) * Number(item.quantity || 1))}</strong>
          </div>`).join("")}</div>
        <div class="plan-budget-grid">
          <span>Budget<strong>${plan.budget == null ? "No limit" : formatCurrency(plan.budget)}</strong></span>
          <span>Savings<strong class="positive">${formatCurrency(plan.savings)}</strong></span>
          <span>Remaining<strong>${plan.remaining_budget == null ? "Not set" : formatCurrency(plan.remaining_budget)}</strong></span>
          <span class="plan-total">Plan total<strong>${formatCurrency(plan.total)}</strong></span>
        </div>
        <div class="plan-approval-note"><span aria-hidden="true">!</span><p><strong>Your approval is required</strong>Nothing will be ordered until you approve this plan.${plan.expires_at ? ` Plan valid until ${escapeHtml(formatDate(plan.expires_at, { dateStyle: "medium", timeStyle: "short" }))}.` : ""}</p></div>
        ${pending ? `<button class="plan-approve-button" type="button" data-plan-approve="${escapeHtml(approvalValue)}" data-plan-id="${escapeHtml(plan.id || "")}" data-plan-token="${escapeHtml(plan.token || "")}" ${approvalValue ? "" : "disabled"}>Approve &amp; order ${formatCurrency(plan.total)}</button>` : ""}
      </section>`;
  }

  function chatServiceRequestHTML(request) {
    const type = request.type === "Exchange" ? "Exchange" : "Return";
    const product = findProduct(request.product_id);
    const icon = product ? productIcon(product) : "\u{1F4E6}";
    const scheduleLabel = type === "Exchange" ? "Replacement ETA" : "Pickup date";
    const scheduleValue = type === "Exchange" ? request.replacement_eta : request.pickup_date;
    return `
      <section class="chat-service-card ${type.toLowerCase()}" role="status" aria-label="${escapeHtml(type)} request ${escapeHtml(request.status || "created")}">
        <header class="service-card-header">
          <span class="service-card-icon" aria-hidden="true">${type === "Exchange" ? "&#8644;" : "&#8630;"}</span>
          <span class="service-card-title"><strong>${escapeHtml(type)} requested</strong><small>${escapeHtml(request.id || "")} &middot; Order ${escapeHtml(request.order_id || "")}</small></span>
          <span class="service-status">${escapeHtml(request.status || "Requested")}</span>
        </header>
        <div class="service-product-row">
          <span class="service-product-icon" aria-hidden="true">${escapeHtml(icon)}</span>
          <span><strong>${escapeHtml(request.product_name || product?.name || "Order item")}</strong><small>Quantity ${numberOr(request.quantity, 1)}${request.reason ? ` &middot; ${escapeHtml(request.reason)}` : ""}</small></span>
        </div>
        <div class="service-result-grid">
          <span>${escapeHtml(scheduleLabel)}<strong>${formatDate(scheduleValue, { dateStyle: "medium" })}</strong></span>
          ${type === "Return" ? `<span>Expected refund<strong>${formatCurrency(request.refund_amount)}</strong></span>` : `<span>Resolution<strong>Replacement item</strong></span>`}
        </div>
        <div class="service-card-actions">
          <button type="button" data-service-prompt="Track ${escapeHtml(type.toLowerCase())} request ${escapeHtml(request.id || "")} for order ${escapeHtml(request.order_id || "")}">Track request</button>
          <button class="secondary" type="button" data-chat-open-orders>View order</button>
        </div>
      </section>`;
  }

  function chatProductCardHTML(product) {
    const evidence = toArray(product.evidence).filter(Boolean);
    return `
      <div class="chat-product-card">
        <span class="chat-product-icon theme-${safeTheme(product.theme)}" aria-hidden="true">${escapeHtml(productIcon(product))}</span>
        <span class="chat-product-copy"><strong>${escapeHtml(product.name)}</strong><small>${escapeHtml(cleanDisplayText(product.short_spec || product.category || ""))}</small><b>${formatCurrency(product.price)}</b></span>
        <button class="chat-card-action" type="button" data-chat-product="${escapeHtml(product.id)}">View</button>
        ${evidence.length ? `<details class="recommendation-evidence"><summary>Why this recommendation?</summary><ul>${evidence.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></details>` : ""}
      </div>`;
  }

  function chatOrderCardHTML(order, context = {}) {
    const firstItem = order.items?.[0] || {};
    const successTitle = context.placed ? "Order placed" : context.cancelled || order.status === "Cancelled" ? "Order cancelled" : "Order update";
    const icon = context.placed ? `<svg viewBox="0 0 24 24"><path d="m7 12 3 3 7-7M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z"/></svg>` : escapeHtml(itemIcon(firstItem));
    return `
      <div class="chat-order-card ${context.placed ? "chat-order-success" : ""}">
        <div class="chat-order-top">
          <span class="chat-order-icon" aria-hidden="true">${icon}</span>
          <span class="chat-order-title"><strong>${escapeHtml(successTitle)}</strong><small>${escapeHtml(order.id || "")} &middot; ${escapeHtml(firstItem.name || "Order")}</small></span>
          <span class="order-status-pill ${statusClass(order.status)}">${escapeHtml(order.status || "Updated")}</span>
        </div>
        <div class="chat-order-meta">
          <span>Total<strong>${formatCurrency(order.total)}</strong></span>
          <span>${order.status === "Delivered" ? "Delivered" : "Expected"}<strong>${formatDate(order.estimated_delivery || order.updated_at, { dateStyle: "medium" })}</strong></span>
        </div>
        <div class="chat-order-actions">
          ${ACTIVE_ORDER_STATUSES.has(order.status) ? `<button type="button" data-chat-prompt="Track order ${escapeHtml(order.id)}">Track order</button>` : ""}
          <button class="secondary" type="button" data-chat-open-orders>View orders</button>
        </div>
      </div>`;
  }

  function renderActionLog(actions) {
    return `
      <details class="action-log">
        <summary><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 9.8 8.8 4 11l5.8 2.2L12 19l2.2-5.8L20 11l-5.8-2.2L12 3Z"/></svg> Action log &middot; ${actions.length} step${actions.length === 1 ? "" : "s"}</summary>
        <div class="action-log-rows">${actions.map((action) => {
          const ok = action.result?.ok !== false;
          const summary = action.result?.shopping_plan ? "Prepared a shopping plan" : action.summary || humanToolName(action.tool);
          return `<div class="action-log-row"><span class="action-check">${ok ? "&#10003;" : "!"}</span><span><strong>${escapeHtml(summary)}</strong>${escapeHtml(actionDetail(action))}</span></div>`;
        }).join("")}</div>
      </details>`;
  }

  function actionDetail(action) {
    const result = action.result || {};
    if (result.error) return result.error;
    if (action.tool === "search_products") return `${numberOr(result.count, result.products?.length || 0)} matching products`;
    if (action.tool === "check_product_availability") return result.can_fulfil === false ? `Only ${numberOr(result.available_stock, 0)} available` : `${numberOr(result.available_stock, 0)} units available`;
    if (["place_order", "checkout_cart"].includes(action.tool)) return result.shopping_plan ? `${result.shopping_plan.id || "Plan"} awaiting approval` : result.order?.id || "Order saved to the local store";
    if (action.tool === "cancel_order") return result.order?.id || "Order state updated";
    if (action.tool === "create_shopping_plan") return `${result.shopping_plan?.id || result.plan?.id || "Plan"} awaiting approval`;
    if (action.tool === "approve_purchase") return result.order?.id || "Approved plan converted into an order";
    if (action.tool === "create_return_request") {
      const request = result.return_request || result.request || {};
      return `${request.id || request.type || "Service request"} ${String(request.status || "created").toLowerCase()}`;
    }
    if (action.tool === "get_order_status") return result.order?.status || "Timeline retrieved";
    if (action.tool === "list_orders") return `${numberOr(result.count, result.orders?.length || 0)} orders retrieved`;
    if (action.tool === "check_return_eligibility") return result.eligible ? `${numberOr(result.items?.length, 0)} item option(s) eligible` : result.reason || "Not currently eligible";
    if (action.tool === "search_faq") return `${numberOr(result.count, result.faqs?.length || 0)} policy answer(s) found`;
    if (action.tool === "summarize_product_reviews") return `${numberOr(result.review_summary?.review_count, 0)} verified reviews summarized`;
    if (action.tool === "list_support_tickets") return `${numberOr(result.count, result.tickets?.length || 0)} ticket(s) retrieved`;
    if (action.tool === "create_support_ticket") return `${result.ticket?.id || "Ticket"} created`;
    if (action.tool === "escalate_support_ticket") return `${result.ticket?.id || "Ticket"} assigned to ${result.ticket?.assigned_to || "a human agent"}`;
    if (action.tool === "compare_products") return `${numberOr(result.products?.length, 0)} grounded products compared`;
    if (action.tool === "manage_cart") return `${numberOr(result.cart?.item_count, 0)} item(s) now in cart`;
    if (action.tool === "manage_preferences") return result.cleared ? "Memory erased" : "Preference controls updated";
    if (action.tool === "recommend_with_constraints") return `${numberOr(result.count, 0)} grounded matches`;
    if (action.tool === "prepare_order_modification") return `${result.modification?.id || "Change"} awaiting confirmation`;
    if (action.tool === "approve_order_modification") return `${result.modification?.id || "Change"} applied`;
    if (action.tool === "get_proactive_assistance") return `${numberOr(result.assistance?.length, 0)} order(s) need attention`;
    if (action.tool === "reason_post_delivery_resolution") return result.recommended_resolution || "Policy evaluated";
    return "Completed using live demo data";
  }

  async function resetDemo() {
    const confirmed = window.confirm("Reset demo orders and clear the agent conversation? This restores the three sample orders.");
    if (!confirmed || state.chatBusy) return;
    refs.resetDemoButton.disabled = true;
    try {
      const payload = await apiFetch("/api/reset", {
        method: "POST",
        body: JSON.stringify({ session_id: state.sessionId }),
      });
      state.sessionId = createSessionId();
      saveSessionId(state.sessionId);
      clearConversationUI();
      state.orders = Array.isArray(payload.orders) ? payload.orders : [];
      await Promise.all([loadProducts({ quiet: true }), loadOrders({ quiet: true })]);
      showToast("Demo reset", payload.message || "Sample orders and agent context were restored.", "info");
    } catch (error) {
      showToast("Could not reset demo", error.message, "error");
    } finally {
      refs.resetDemoButton.disabled = false;
    }
  }

  function clearConversationUI() {
    refs.agentMessages.querySelectorAll(".chat-message:not(.welcome-message)").forEach((node) => node.remove());
    refs.suggestedPrompts.hidden = false;
    refs.agentInput.value = "";
    autoGrowInput();
    updateSendButton();
  }

  function setAgentMode(mode, model = "") {
    const statusDot = document.querySelector(".footer-status-dot");
    const normalized = String(mode || "").toLowerCase();
    if (normalized === "remote") {
      refs.agentModeLabel.textContent = `${model || "GPT-4.1 Nano"} connected`;
      statusDot?.classList.add("connected");
    } else if (normalized === "offline") {
      refs.agentModeLabel.textContent = "Server unavailable";
      statusDot?.classList.remove("connected");
    } else {
      refs.agentModeLabel.textContent = "Local fallback ready";
      statusDot?.classList.add("connected");
    }
  }

  async function openInsights() {
    if (!state.user) { openAuth(); return; }
    state.lastFocus = document.activeElement;
    refs.insightsLayer.hidden = false;
    syncBodyLayerState();
    await loadInsights();
  }

  function closeInsights() {
    refs.insightsLayer.hidden = true;
    syncBodyLayerState();
  }

  async function loadInsights() {
    refs.traceList.innerHTML = `<div class="drawer-loading"><span class="spinner"></span> Loading traces&hellip;</div>`;
    try {
      const [tracePayload, metricPayload] = await Promise.all([apiFetch("/api/agent/traces?limit=50"), apiFetch("/api/agent/metrics")]);
      const metrics = metricPayload.metrics || {};
      refs.traceMetrics.innerHTML = [
        ["Scenarios", metrics.scenario_count || 0], ["Successful", metrics.success_count || 0],
        ["Average latency", `${metrics.average_latency_ms || 0} ms`], ["Total tokens", metrics.total_tokens || 0],
        ["Estimated cost", `$${Number(metrics.estimated_cost_usd || 0).toFixed(6)}`],
      ].map(([label, value]) => `<span><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></span>`).join("");
      const traces = toArray(tracePayload.traces);
      refs.traceList.innerHTML = traces.length ? traces.map(traceListHTML).join("") : `<p class="empty-traces">No traces yet. Ask Volt a question to create one.</p>`;
    } catch (error) { refs.traceList.innerHTML = `<p class="empty-traces">${escapeHtml(error.message)}</p>`; }
  }

  function traceListHTML(trace) {
    const prompt = encodeURIComponent(trace.user_message || "");
    const tools = toArray(trace.actions).map((action) => humanToolName(action.tool)).join(" → ") || "No tool selected";
    return `<details class="trace-row">
      <summary><span><strong>${escapeHtml(trace.intent)}</strong><small>${escapeHtml(trace.correlation_id)} &middot; ${escapeHtml(trace.mode)} / ${escapeHtml(trace.model)}</small></span><b>${numberOr(trace.confidence, 0).toFixed(2)}</b></summary>
      <div><p><strong>Prompt:</strong> ${escapeHtml(trace.user_message)}</p><p><strong>Tools:</strong> ${escapeHtml(tools)}</p><p><strong>Guardrails:</strong> ${escapeHtml(toArray(trace.guardrails).map((item) => `${item.check}: ${item.decision}`).join(", "))}</p><p><strong>Outcome:</strong> ${escapeHtml(trace.outcome)} &middot; ${numberOr(trace.latency_ms, 0)} ms &middot; ${numberOr(trace.total_tokens, 0)} tokens &middot; $${Number(trace.estimated_cost_usd || 0).toFixed(6)}</p>${trace.fallback_reason ? `<p><strong>Fallback:</strong> ${escapeHtml(trace.fallback_reason)}</p>` : ""}<button class="button" type="button" data-replay-trace="${escapeHtml(trace.id)}" data-replay-prompt="${escapeHtml(prompt)}">Replay read-only</button></div>
    </details>`;
  }

  async function replayTrace(traceId, encodedPrompt) {
    closeInsights(); openAgent();
    let prompt = "";
    try { prompt = decodeURIComponent(encodedPrompt); } catch (_) { prompt = encodedPrompt; }
    const typing = addTypingMessage("Replay scenario");
    try {
      const data = await apiFetch(`/api/agent/traces/${encodeURIComponent(traceId)}/replay`, { method: "POST", body: JSON.stringify({ prompt, mode: "current" }), timeout: 65000 });
      typing.remove(); addAssistantMessage(data);
      showToast("Trace replayed", "Replay is read-only, so transactional tools were blocked.", "info");
    } catch (error) { typing.remove(); addErrorMessage(error.message); }
  }

  function autoGrowInput() {
    refs.agentInput.style.height = "auto";
    refs.agentInput.style.height = `${Math.min(refs.agentInput.scrollHeight, 96)}px`;
  }

  function updateSendButton() {
    refs.sendAgentButton.disabled = state.chatBusy || !refs.agentInput.value.trim() || refs.agentInput.disabled;
  }

  function scrollChatToBottom() {
    requestAnimationFrame(() => {
      refs.agentMessages.scrollTop = refs.agentMessages.scrollHeight;
    });
  }

  function scrollToProducts() {
    document.getElementById("productsSection").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function syncBodyLayerState() {
    const open = !refs.ordersLayer.hidden || !refs.productModalLayer.hidden || !refs.cartLayer.hidden || !refs.accountLayer.hidden || !refs.insightsLayer.hidden || !refs.authLayer.hidden || !refs.mobileAgentBackdrop.hidden;
    document.body.classList.toggle("layer-open", open);
  }

  function restoreFocus() {
    if (state.lastFocus && typeof state.lastFocus.focus === "function") state.lastFocus.focus();
    state.lastFocus = null;
  }

  function showToast(title, detail = "", type = "success") {
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    const icon = type === "error" ? "!" : type === "info" ? "i" : "&#10003;";
    toast.innerHTML = `<span class="toast-icon">${icon}</span><span class="toast-copy"><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail)}</small></span><button class="toast-close" type="button" aria-label="Dismiss notification"><svg viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18"/></svg></button>`;
    refs.toastRegion.appendChild(toast);
    const remove = () => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(7px)";
      setTimeout(() => toast.remove(), 180);
    };
    toast.querySelector("button").addEventListener("click", remove);
    setTimeout(remove, type === "error" ? 6500 : 4200);
  }

  async function apiFetch(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeout || 20000);
    try {
      const response = await fetch(path, {
        ...options,
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        signal: controller.signal,
      });
      const contentType = response.headers.get("content-type") || "";
      const payload = contentType.includes("application/json") ? await response.json() : { error: await response.text() };
      if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
      return payload;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("The request timed out.");
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function findProduct(id) {
    return state.products.find((product) => product.id === id);
  }

  function availableStock(product) {
    return Math.max(0, Number(product.available_stock ?? product.stock ?? 0));
  }

  function productIcon(product) {
    const icon = String(product.icon || "");
    if (icon && !/[\u00C2\u00C3\u00E2\u00F0]/.test(icon)) return icon;
    return CATEGORY_ICONS[product.category] || "\u{1F4E6}";
  }

  function itemIcon(item) {
    const icon = String(item?.icon || "");
    if (icon && !/[\u00C2\u00C3\u00E2\u00F0]/.test(icon)) return icon;
    const product = item?.product_id ? findProduct(item.product_id) : null;
    return product ? productIcon(product) : "\u{1F4E6}";
  }

  function planItemIcon(item) {
    const icon = String(item?.icon || "");
    if (icon && !/[\u00C2\u00C3\u00E2\u00F0]/.test(icon)) return icon;
    const product = item?.product_id ? findProduct(item.product_id) : null;
    return product ? productIcon(product) : "\u{1F4E6}";
  }

  function safeTheme(theme) {
    const value = String(theme || "blue").toLowerCase();
    return ["sky", "violet", "blue", "mint", "coral", "indigo", "slate", "teal"].includes(value) ? value : "blue";
  }

  function formatCurrency(value) {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(Number(value || 0));
  }

  function formatCount(value) {
    const count = Number(value || 0);
    if (count >= 1000) return `${(count / 1000).toFixed(count >= 10000 ? 0 : 1)}k`;
    return new Intl.NumberFormat("en-IN").format(count);
  }

  function formatDate(value, options = {}) {
    if (!value) return "To be confirmed";
    const source = /^\d{4}-\d{2}-\d{2}$/.test(String(value)) ? `${value}T12:00:00` : value;
    const date = new Date(source);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("en-IN", options).format(date);
  }

  function currentTime() {
    return new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit" }).format(new Date());
  }

  function statusClass(status) {
    return `status-${String(status || "unknown").toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  }

  function humanToolName(tool) {
    return String(tool || "Action completed").replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  }

  function cleanDisplayText(value) {
    return String(value || "").replace(/\u00C2\u00B7/g, "\u00B7").replace(/\u00E2\u20AC\u201C/g, "-").replace(/\s+/g, " ").trim();
  }

  function normalizeText(value) {
    return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  }

  function numberOr(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
    })[character]);
  }

  function formatMessageText(value) {
    return escapeHtml(value).replace(/\n/g, "<br>");
  }

  function toArray(value) {
    if (!value) return [];
    return Array.isArray(value) ? value : [value];
  }

  function uniqueById(items) {
    const seen = new Set();
    return items.filter((item) => {
      const id = item?.id || JSON.stringify(item);
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  }

  function isOrder(value) {
    return Boolean(value && typeof value === "object" && (String(value.id || "").startsWith("ORD-") || Array.isArray(value.items)));
  }

  function isShoppingPlan(value) {
    return Boolean(value && typeof value === "object" && value.id && Array.isArray(value.items));
  }

  function isServiceRequest(value) {
    return Boolean(value && typeof value === "object" && value.id && value.order_id && ["Return", "Exchange"].includes(value.type));
  }

  function isProduct(value) {
    return Boolean(value && typeof value === "object" && value.id && value.name && value.price !== undefined && !Array.isArray(value.items));
  }

  function isSupportTicket(value) {
    return Boolean(value && typeof value === "object" && String(value.id || "").startsWith("SUP-") && value.subject);
  }

  function isMutatingAction(action) {
    return ["place_order", "checkout_cart", "cancel_order", "approve_purchase", "create_return_request", "create_support_ticket", "escalate_support_ticket", "manage_cart", "manage_preferences", "approve_order_modification"].includes(action?.tool);
  }

  function createSessionId() {
    if (globalThis.crypto?.randomUUID) return `volt-${crypto.randomUUID()}`;
    return `volt-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }

  function createMessageId() {
    if (globalThis.crypto?.randomUUID) return `msg-${crypto.randomUUID()}`;
    return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }

  function getOrCreateSessionId() {
    try {
      const existing = sessionStorage.getItem("voltcart-session-id");
      if (existing) return existing;
    } catch (_) {
      // Storage can be unavailable in strict privacy contexts.
    }
    const id = createSessionId();
    saveSessionId(id);
    return id;
  }

  function saveSessionId(id) {
    try {
      sessionStorage.setItem("voltcart-session-id", id);
    } catch (_) {
      // The session still works for the current page without browser storage.
    }
  }
})();
