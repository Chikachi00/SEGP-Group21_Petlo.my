import { useRef } from "react";
import { useParams } from "react-router";

const events = [
  { id: 1, time: 5.2, label: "00:05 🟢 Catch" },
  { id: 2, time: 18.0, label: "00:18 🔴 Failure" },
  { id: 3, time: 31.0, label: "00:31 🟢 Catch" },
  { id: 4, time: 47.3, label: "00:47 ⚪ Indetermination" },
];

export default function ResultPage() {
  const { id } = useParams();
  
  const videoRef = useRef<HTMLVideoElement>(null);

  function jumpTo(time: number) {
    if (!videoRef.current) return;
    videoRef.current.currentTime = time;
    videoRef.current.play();
  }

  return (
    <div>
      <h2>Result details</h2>
      <p>The current video being viewed：{id}</p>

      <video ref={videoRef} src="../../public/test_video.mp4" controls width={480} />

      <ul>
        {events.map((ev) => (
          <li key={ev.id} onClick={() => jumpTo(ev.time)} style={{ cursor: "pointer" }}>
            #{ev.id} {ev.label}
          </li>
        ))}
      </ul>
    </div>
  );
}