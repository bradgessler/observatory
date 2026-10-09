defmodule Controller.Sky.Lock do
  @moduledoc """
  "Will I see it?" in one line: whether a Go To lands close enough for the
  object to be in the eyepiece, from the alignment's margin (twice its rms)
  against the eyepiece's field. Honest when it can't say: one or two points
  can't be judged, and no alignment is not aligned.
  """

  @doc "`{tone, words}` for mount `id`'s alignment status and an eyepiece `field` in arcminutes."
  def words(status, field) do
    case status do
      %{solved?: true, n: n, rms_arcmin: rms} when n >= 3 and is_number(rms) ->
        margin = round(2 * rms)

        if margin < field / 2,
          do:
            {:good,
             "Aligned on #{n} points: lands within ±#{margin}′, and the eyepiece shows #{field}′, so it'll be in view."},
          else:
            {:caution,
             "Loosely aligned: lands within ±#{margin}′, more than the #{field}′ eyepiece shows. Expect to use Spiral Search."}

      %{solved?: true, n: n} ->
        {:caution,
         "Aligned on #{n} point#{if n == 1, do: "", else: "s"}: too few to measure the margin. Center one more object and tap Centered."}

      _ ->
        {:off, "Not aligned yet. Center any star or planet and tap Centered."}
    end
  end
end
