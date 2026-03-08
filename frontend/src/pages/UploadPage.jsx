import { useState } from "react";
import axios from "axios";

function UploadPage() {
  const [file, setFile] = useState(null);

  const uploadFile = async () => {
    if (!file) {
      alert("Please choose a file first");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await axios.post(
        "http://localhost:5001/upload_orders",
        formData,
        {
          headers: {
            "Content-Type": "multipart/form-data",
          },
        }
      );

      alert("Orders Loaded: " + res.data.rows_inserted);
    } catch (err) {
      console.error(err);

      const msg =
        err?.response?.data?.error ||
        err?.message ||
        "Upload failed";

      alert(msg);
    }
  };

  return (
    <div>
      <h2>Upload Orders Excel</h2>

      <input
        type="file"
        onChange={(e) => setFile(e.target.files[0] || null)}
      />

      <br />
      <br />

      <button onClick={uploadFile}>Upload Orders</button>
    </div>
  );
}

export default UploadPage;