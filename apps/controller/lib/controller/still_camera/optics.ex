defmodule Controller.StillCamera.Optics do
  @moduledoc """
  The telescope's focal length, and where the number came from.

  The number on the tube is a label: an 8SE says 2,032 mm, and plate solves
  of its pictures said 2,084 (a Schmidt-Cassegrain's focal length moves with
  where its mirror sits and with what is screwed on behind it). A solved
  picture measures it: the solver says how much sky a pixel covers, the
  sensor says how big a pixel is, and the focal length is one over the
  other.

      Optics.focal_length_mm(0.388, 3.917)
      #=> 2082.3
      Optics.focal_length()
      #=> %{mm: 2082.3, from: "solve", label_mm: 2032}

  It is kept where the optics are, in `Controller.Settings`:

    * `"focal_length_mm"` is the one in force. Whatever reads the focal
      length (the scale handed to the solver, star size in arcseconds, a
      picture's sidecar) reads this, so a measured one reaches all of them.
    * `"focal_length_solved"` is the record of the solve that measured it:
      the number, the label it took the place of, the scale and the pixel it
      came from, and when.

  The focal length is "from the solve" for as long as those two agree. Put
  another number in `"focal_length_mm"` (another telescope, a reducer) and
  it is a label again, until the next solve measures that one.

  The first solve is the one that is kept (`learn/3`); `again: true` takes a
  later one instead.
  """

  alias Controller.Settings

  # arcseconds in a radian, over the thousand microns in a millimetre
  @k 206.264806

  @doc """
  The focal length, in mm, that puts `arcsec_per_px` of sky on a pixel
  `pixel_um` microns across. `nil` unless both are positive numbers.

  The scale and the pixel must be of the same picture: a JPEG the camera
  made at half size covers twice the sky per pixel with pixels twice as big.
  """
  def focal_length_mm(arcsec_per_px, pixel_um) when is_number(arcsec_per_px) and is_number(pixel_um) and arcsec_per_px > 0 and pixel_um > 0,
    do: @k * pixel_um / arcsec_per_px

  def focal_length_mm(_, _), do: nil

  @doc """
  The focal length in force and where it came from: `%{mm:, from: "solve"}`
  with `label_mm:` (the label it took the place of, when there was one), or
  `%{mm:, from: "label"}`. `nil` when none is set.
  """
  def focal_length do
    case {Settings.get("focal_length_mm"), Settings.get("focal_length_solved")} do
      {mm, %{"mm" => mm} = solved} when is_number(mm) and mm > 0 ->
        if is_number(solved["label_mm"]), do: %{mm: mm, from: "solve", label_mm: solved["label_mm"]}, else: %{mm: mm, from: "solve"}

      {mm, _} when is_number(mm) and mm > 0 ->
        %{mm: mm, from: "label"}

      _ ->
        nil
    end
  end

  @doc """
  Take the focal length from a solve: `arcsec_per_px` as solved, `pixel_um`
  the pixel of the same picture. `{:ok, mm}` when it became the focal length
  in force; `:kept` when one from a solve already is (the first solve is the
  one kept); `{:error, :no_scale}` when the numbers give none.

  Options: `again: true` to take this solve whatever is there, and `plate:`
  (anything that says which solve it was), kept in the record.
  """
  def learn(arcsec_per_px, pixel_um, opts \\ []) do
    now = focal_length()
    again? = opts[:again] == true

    case focal_length_mm(arcsec_per_px, pixel_um) do
      nil ->
        {:error, :no_scale}

      _ when is_map(now) and now.from == "solve" and not again? ->
        :kept

      mm ->
        mm = Float.round(mm, 1)
        # the label under a measured one stays the label, however often it is measured again
        label = if now, do: now[:label_mm] || (now.from == "label" && now.mm) || nil

        record = %{"mm" => mm, "label_mm" => label, "arcsec_per_px" => Float.round(arcsec_per_px / 1, 5), "pixel_um" => Float.round(pixel_um / 1, 4), "plate" => opts[:plate], "at" => DateTime.to_iso8601(DateTime.utc_now())}
        Settings.put("focal_length_solved", Map.reject(record, fn {_, v} -> v == nil end))
        Settings.put("focal_length_mm", mm)
        {:ok, mm}
    end
  end
end
