import "./styles/index.css";

import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import AppLayout from "./layouts/AppLayout";
import { LoginPage, SignupPage, VerifyOtpPage } from "./pages/Auth";
import Dashboard from "./pages/Dashboard";
import { AlertsPage, DataPage, FiresPage, HistoricalPage, LogsPage, RiskPage, SettingsPage } from "./pages/Misc";
import ModelsPage from "./pages/Models";
import SimulationPage from "./pages/Simulation";

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/signup", element: <SignupPage /> },
  { path: "/verify", element: <VerifyOtpPage /> },
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: "simulation", element: <SimulationPage /> },
      { path: "data", element: <DataPage /> },
      { path: "models", element: <ModelsPage /> },
      { path: "logs", element: <LogsPage /> },
      { path: "fires", element: <FiresPage /> },
      { path: "alerts", element: <AlertsPage /> },
      { path: "risk", element: <RiskPage /> },
      { path: "historical", element: <HistoricalPage /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
);
