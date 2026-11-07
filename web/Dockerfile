# ---------- Web tier: Nginx reverse proxy + static assets ----------
FROM nginx:1.27-alpine

# Replace the default site with ours
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/expense.conf

# Static front-end assets (CSS/JS)
COPY static/ /usr/share/nginx/html/static/

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD wget -qO- http://127.0.0.1/nginx-health || exit 1
