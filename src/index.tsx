import { ButtonItem, PanelSection, PanelSectionRow, ToggleField, staticClasses } from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

interface ServiceStatus {
  installed: boolean;
  active: boolean;
  state: string;
  error?: string;
}

const getServiceStatus = callable<[], ServiceStatus>("get_service_status");
const setServiceEnabled = callable<[enabled: boolean], ServiceStatus>("set_service_enabled");

function GamepadIcon() {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor">
      <path d="M7 6h10a5 5 0 0 1 4.8 6.4l-1.3 4.4a2.8 2.8 0 0 1-4.6 1.3L14 16h-4l-1.9 2.1a2.8 2.8 0 0 1-4.6-1.3l-1.3-4.4A5 5 0 0 1 7 6Zm-.5 3v2H4.5v2h2v2h2v-2h2v-2h-2V9h-2Zm9.5 2a1 1 0 1 0 0 2 1 1 0 0 0 0-2Zm2.5 2a1 1 0 1 0 0 2 1 1 0 0 0 0-2Z" />
    </svg>
  );
}

function Content() {
  const [status, setStatus] = useState<ServiceStatus>({
    installed: true,
    active: false,
    state: "loading",
  });
  const [busy, setBusy] = useState(true);

  const refresh = useCallback(async (showError = false) => {
    try {
      const nextStatus = await getServiceStatus();
      setStatus(nextStatus);
      if (showError && nextStatus.error) {
        toaster.toast({ title: "Legion Go Gyro DSU", body: nextStatus.error });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus({ installed: false, active: false, state: "error", error: message });
      if (showError) {
        toaster.toast({ title: "Legion Go Gyro DSU", body: message });
      }
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void refresh(true);
  }, [refresh]);

  const toggleService = async (enabled: boolean) => {
    const previousStatus = status;
    setBusy(true);
    setStatus({ ...status, active: enabled, state: enabled ? "starting" : "stopping" });

    try {
      const nextStatus = await setServiceEnabled(enabled);
      setStatus(nextStatus);
      if (nextStatus.error) {
        throw new Error(nextStatus.error);
      }
      toaster.toast({
        title: "Legion Go Gyro DSU",
        body: nextStatus.active ? "Motion server started" : "Motion server stopped",
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus(previousStatus);
      toaster.toast({ title: "Unable to change service state", body: message });
      await refresh(false);
    } finally {
      setBusy(false);
    }
  };

  const description = !status.installed
    ? "lgsdsu.service is not installed"
    : busy
      ? status.state === "loading" ? "Checking service status…" : `${status.state}…`
      : status.active ? "DSU motion server is running" : `DSU motion server is ${status.state}`;

  return (
    <PanelSection title="Motion Server">
      <PanelSectionRow>
        <ToggleField
          label="Legion Go Gyro DSU"
          description={description}
          checked={status.active}
          disabled={busy || !status.installed}
          onChange={(enabled) => void toggleService(enabled)}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={() => void refresh(true)}>
          Refresh status
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

export default definePlugin(() => ({
  name: "Legion Go Gyro DSU",
  titleView: <div className={staticClasses.Title}>Legion Go Gyro DSU</div>,
  content: <Content />,
  icon: <GamepadIcon />,
}));
