import { ButtonItem, PanelSection, PanelSectionRow, ToggleField, staticClasses } from "@decky/ui";
import { addEventListener, callable, definePlugin, removeEventListener, toaster } from "@decky/api";
import { Fragment, useCallback, useEffect, useState } from "react";

interface ServiceStatus {
  installed: boolean;
  active: boolean;
  state: string;
  error?: string;
}

interface StreamStatus {
  started: boolean;
  error?: string;
}

interface Orientation {
  roll: number;
  pitch: number;
  yaw: number;
}

interface MotionConnection {
  connected: boolean;
  error?: string;
}

const getServiceStatus = callable<[], ServiceStatus>("get_service_status");
const setServiceEnabled = callable<[enabled: boolean], ServiceStatus>("set_service_enabled");
const startMotionStream = callable<[], StreamStatus>("start_motion_stream");
const stopMotionStream = callable<[], StreamStatus>("stop_motion_stream");
const recenterMotion = callable<[], void>("recenter_motion");

const viewerStyle = {
  height: "150px",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  perspective: "500px",
  overflow: "hidden",
  borderRadius: "8px",
  background: "radial-gradient(circle at center, rgba(88, 155, 255, 0.18), rgba(0, 0, 0, 0.2))",
};

const deviceStyle = {
  width: "176px",
  height: "72px",
  position: "relative" as const,
  transformStyle: "preserve-3d" as const,
  transformOrigin: "50% 50%",
  transition: "transform 45ms linear",
};

const faceStyle = {
  position: "absolute" as const,
  boxSizing: "border-box" as const,
  backfaceVisibility: "hidden" as const,
};

function DeviceModel({ orientation }: { orientation: Orientation }) {
  const transform = `rotateX(${orientation.pitch.toFixed(2)}deg) rotateY(${orientation.yaw.toFixed(2)}deg) rotateZ(${(-orientation.roll).toFixed(2)}deg)`;
  return (
    <div style={viewerStyle}>
      <div style={{ ...deviceStyle, transform }}>
        <div style={{ ...faceStyle, inset: 0, transform: "translateZ(9px)", borderRadius: "16px", background: "#171d25", boxShadow: "0 12px 22px rgba(0,0,0,.5)" }}>
          <div style={{ position: "absolute", inset: "8px 25px", borderRadius: "8px", background: "#242b35", border: "2px solid #748293" }}>
            <div style={{ position: "absolute", inset: "7px 10px", borderRadius: "3px", background: "linear-gradient(135deg, #387cc7, #67d3ca)" }} />
          </div>
          <div style={{ position: "absolute", left: 0, top: 3, width: 35, height: 66, borderRadius: "16px 6px 6px 16px", background: "#202732", border: "2px solid #748293" }}>
            <div style={{ position: "absolute", left: 10, top: 16, width: 13, height: 13, borderRadius: "50%", background: "#0d1117", border: "2px solid #8995a3" }} />
          </div>
          <div style={{ position: "absolute", right: 0, top: 3, width: 35, height: 66, borderRadius: "6px 16px 16px 6px", background: "#202732", border: "2px solid #748293" }}>
            <div style={{ position: "absolute", right: 10, top: 31, width: 13, height: 13, borderRadius: "50%", background: "#0d1117", border: "2px solid #8995a3" }} />
          </div>
        </div>
        <div style={{ ...faceStyle, inset: 0, transform: "rotateY(180deg) translateZ(9px)", borderRadius: "16px", background: "linear-gradient(145deg, #11161d, #2d3743)", border: "2px solid #596573" }}>
          <div style={{ position: "absolute", inset: "13px 42px", borderRadius: "6px", border: "1px solid #46515d", background: "#181f27" }} />
        </div>
        <div style={{ ...faceStyle, left: 0, top: 27, width: 176, height: 18, transform: "rotateX(90deg) translateZ(36px)", background: "linear-gradient(90deg, #27313c, #657789, #27313c)", border: "1px solid #8291a0" }}>
          <div style={{ position: "absolute", left: 68, right: 68, top: 2, height: 3, borderRadius: "2px", background: "#69e0d2", boxShadow: "0 0 5px rgba(105,224,210,.8)" }} />
        </div>
        <div style={{ ...faceStyle, left: 0, top: 27, width: 176, height: 18, transform: "rotateX(-90deg) translateZ(36px)", background: "#111820", border: "1px solid #3d4854" }} />
        <div style={{ ...faceStyle, left: 79, top: 0, width: 18, height: 72, transform: "rotateY(-90deg) translateZ(88px)", background: "linear-gradient(#303b47, #151b22)", border: "1px solid #596675" }} />
        <div style={{ ...faceStyle, left: 79, top: 0, width: 18, height: 72, transform: "rotateY(90deg) translateZ(88px)", background: "linear-gradient(#303b47, #151b22)", border: "1px solid #596675" }} />
      </div>
    </div>
  );
}

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
  const [live, setLive] = useState(false);
  const [motionConnected, setMotionConnected] = useState(false);
  const [motionError, setMotionError] = useState<string>();
  const [orientation, setOrientation] = useState<Orientation>({ roll: 0, pitch: 0, yaw: 0 });

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

  useEffect(() => {
    const sampleListener = addEventListener<[Orientation]>("motion_sample", setOrientation);
    const connectionListener = addEventListener<[MotionConnection]>("motion_connection", (connection) => {
      setMotionConnected(connection.connected);
      setMotionError(connection.error);
    });
    return () => {
      removeEventListener("motion_sample", sampleListener);
      removeEventListener("motion_connection", connectionListener);
      void stopMotionStream();
    };
  }, []);

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
      if (!nextStatus.active) {
        setLive(false);
        setMotionConnected(false);
        setOrientation({ roll: 0, pitch: 0, yaw: 0 });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus(previousStatus);
      toaster.toast({ title: "Unable to change service state", body: message });
      await refresh(false);
    } finally {
      setBusy(false);
    }
  };

  const toggleLive = async (enabled: boolean) => {
    setMotionError(undefined);
    if (!enabled) {
      setLive(false);
      setMotionConnected(false);
      await stopMotionStream();
      return;
    }

    setLive(true);
    try {
      const result = await startMotionStream();
      if (!result.started) {
        throw new Error(result.error ?? "Unable to start the DSU live view");
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setLive(false);
      setMotionError(message);
      toaster.toast({ title: "Unable to start live rotation", body: message });
    }
  };

  const description = status.error
    ? status.error
    : !status.installed
    ? "lgsdsu.service is not installed"
    : busy
      ? status.state === "loading" ? "Checking service status…" : `${status.state}…`
      : status.active ? "DSU motion server is running" : `DSU motion server is ${status.state}`;

  const liveDescription = motionError
    ? motionError
    : !live
      ? "No additional network or rendering activity"
      : motionConnected
        ? "Receiving motion data from localhost"
        : "Waiting for DSU motion data…";

  return (
    <Fragment>
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
      <PanelSection title="Live Rotation">
        <PanelSectionRow>
          <ToggleField
            label="Show device orientation"
            description={liveDescription}
            checked={live}
            disabled={!status.active || busy}
            onChange={(enabled) => void toggleLive(enabled)}
          />
        </PanelSectionRow>
        {live && (
          <Fragment>
            <PanelSectionRow>
              <DeviceModel orientation={orientation} />
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => void recenterMotion()}>
                Recenter orientation
              </ButtonItem>
            </PanelSectionRow>
          </Fragment>
        )}
      </PanelSection>
    </Fragment>
  );
}

export default definePlugin(() => ({
  name: "Legion Go Gyro DSU",
  titleView: <div className={staticClasses.Title}>Legion Go Gyro DSU</div>,
  content: <Content />,
  icon: <GamepadIcon />,
}));
