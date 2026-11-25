import { currentMonitor, getCurrentWindow, LogicalSize, PhysicalPosition } from "@tauri-apps/api/window";

type NativeWindow = ReturnType<typeof getCurrentWindow>;
type SavedWindow = {
  maximized: boolean;
  position: Awaited<ReturnType<NativeWindow["outerPosition"]>>;
  size: Awaited<ReturnType<NativeWindow["innerSize"]>>;
};

const CAPSULE = { width: 224, height: 50 };

export async function restoreWindow(saved: SavedWindow) {
  const native = getCurrentWindow();
  await native.setResizable(true);
  await native.setMinSize(new LogicalSize(640, 480));
  await native.setSize(saved.size);
  await native.setPosition(saved.position);
  if (saved.maximized) await native.maximize();
  await native.setAlwaysOnTop(false);
}

export async function shrinkWindow(): Promise<SavedWindow> {
  const native = getCurrentWindow();
  const [maximized, monitor, scale] = await Promise.all([
    native.isMaximized(), currentMonitor(), native.scaleFactor(),
  ]);
  if (maximized) await native.unmaximize();

  let saved: SavedWindow | undefined;
  try {
    const [position, size] = await Promise.all([native.outerPosition(), native.innerSize()]);
    saved = { maximized, position, size };
    await native.setMinSize(null);
    await native.setSize(new LogicalSize(CAPSULE.width, CAPSULE.height));
    if (monitor) {
      const { position: corner, size: area } = monitor.workArea;
      await native.setPosition(new PhysicalPosition(
        corner.x + area.width - Math.round((CAPSULE.width + 16) * scale),
        corner.y + area.height - Math.round((CAPSULE.height + 16) * scale),
      ));
    }
    await native.setResizable(false);
    await native.setAlwaysOnTop(true);
    return saved;
  } catch (error) {
    if (saved) await restoreWindow(saved);
    else if (maximized) await native.maximize();
    throw error;
  }
}
