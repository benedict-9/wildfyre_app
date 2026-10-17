// /app/ shares the API origin; edit the separate-host URL when needed.
window.WILDFYRE_CONFIG={apiBaseUrl:window.location.pathname.startsWith('/app/')?window.location.origin:'http://127.0.0.1:8000'};
