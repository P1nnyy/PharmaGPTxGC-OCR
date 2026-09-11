"""The schedule, the next action, the timeline and the reminders.

Two behaviours get the most attention because they are the ones that decide
whether the feature is useful or ignored:

  the **next action** must be one thing, and must put a return about to become
  permanently unfileable above one merely due next week;

  **reminders must stay quiet** unless somebody asked for them, and must
  escalate rather than repeat.
"""

from datetime import date, timedelta

import pytest

from core.gst_calendar import GSTR1, GSTR3B
from services.compliance import reminders, schedule, stages

TODAY = date(2026, 9, 11)


def items_for(fy=2026, frequency="MONTHLY", completion=None):
    return schedule.build_schedule(fy, frequency, "27", TODAY, completion or {})


class TestSchedule:
    def test_marks_what_is_already_done(self):
        items = items_for(completion={
            ("042026", GSTR1): {"is_done": True, "arn": "AA270426000001X", "done_at": "2026-05-09"},
        })
        done = next(i for i in items if i.obligation.period == "042026"
                    and i.obligation.kind == GSTR1)
        assert done.is_done is True
        assert done.arn == "AA270426000001X"

    def test_urgency_reads_off_the_due_date(self):
        items = items_for()
        august_1 = next(i for i in items if i.obligation.period == "082026"
                        and i.obligation.kind == GSTR1)
        # Due 2026-09-11 - today.
        assert august_1.days_remaining(TODAY) == 0
        assert august_1.urgency(TODAY) == "URGENT"

    def test_a_completed_obligation_is_never_urgent(self):
        items = items_for(completion={("082026", GSTR1): {"is_done": True}})
        august_1 = next(i for i in items if i.obligation.period == "082026"
                        and i.obligation.kind == GSTR1)
        assert august_1.urgency(TODAY) == "DONE"

    def test_gstr2b_is_informational_rather_than_due(self):
        items = items_for()
        block = next(i for i in items if i.obligation.kind == "GSTR2B")
        assert block.urgency(TODAY) == "INFORMATIONAL"


class TestNextAction:
    def test_names_exactly_one_thing(self):
        action = schedule.next_action(items_for(), TODAY)
        assert isinstance(action, dict)
        assert action["kind"] and action["headline"]

    def test_picks_the_soonest_due_when_nothing_is_late(self):
        # Everything before September filed, so the next thing is ahead of us.
        completion = {
            (period, kind): {"is_done": True}
            for period in ("042026", "052026", "062026", "072026", "082026")
            for kind in (GSTR1, GSTR3B)
        }
        action = schedule.next_action(items_for(completion=completion), TODAY)
        assert action["reason"] == "NEXT_DUE"
        assert action["period"] == "092026"
        assert action["kind"] == GSTR1
        assert "due in 30 days" in action["headline"]

    def test_an_overdue_return_outranks_one_merely_due(self):
        action = schedule.next_action(items_for(), TODAY)
        assert action["reason"] == "OVERDUE"
        assert "Late fees are running" in action["headline"]

    def test_an_approaching_permanent_bar_outranks_everything(self):
        # A 2023 return with nine days left before it can never be filed beats
        # a 2026 one that is merely late.
        both = items_for(fy=2023) + items_for(fy=2026)
        action = schedule.next_action(both, TODAY)
        assert action["reason"] == "TIME_BAR"
        assert action["period"] == "082023"
        assert "refuses it permanently" in action["headline"]

    def test_nothing_left_to_do_is_a_real_answer(self):
        completion = {
            (i.obligation.period, i.obligation.kind): {"is_done": True}
            for i in items_for()
        }
        assert schedule.next_action(items_for(completion=completion), TODAY) is None

    def test_a_barred_return_is_not_offered_as_an_action(self):
        # It cannot be filed, so naming it as the next thing to do would be
        # naming something with nothing to do in it.
        action = schedule.next_action(items_for(fy=2022), TODAY)
        assert action is None

    def test_the_headline_reads_as_a_sentence(self):
        completion = {
            (p, k): {"is_done": True}
            for p in ("042026", "052026", "062026", "072026") for k in (GSTR1, GSTR3B)
        }
        completion[("082026", GSTR1)] = {"is_done": True}
        action = schedule.next_action(items_for(completion=completion), TODAY)
        assert action["headline"].endswith(".")
        assert action["headline"][0].isupper()


class TestTimeBarWatch:
    def test_separates_what_is_already_lost_from_what_is_closing(self):
        watch = schedule.time_barred_watch([], TODAY, historic=items_for(fy=2023))
        assert watch["already_barred_count"] == 8
        assert watch["closing_soon_count"] == 11
        assert watch["has_anything"] is True

    def test_orders_the_closing_ones_by_how_little_time_is_left(self):
        watch = schedule.time_barred_watch([], TODAY, historic=items_for(fy=2023))
        remaining = [r["days_until_barred"] for r in watch["closing_soon"]]
        assert remaining == sorted(remaining)
        assert remaining[0] == 9

    def test_cites_the_sections_behind_the_rule(self):
        watch = schedule.time_barred_watch([], TODAY)
        assert "39(11)" in watch["rule"] and "37(4)" in watch["rule"]
        assert "no condonation" in watch["rule"]

    def test_a_filed_period_is_not_at_risk(self):
        completion = {
            (i.obligation.period, i.obligation.kind): {"is_done": True}
            for i in items_for(fy=2023)
        }
        watch = schedule.time_barred_watch(
            [], TODAY, historic=items_for(fy=2023, completion=completion)
        )
        assert watch["has_anything"] is False

    def test_open_years_stop_where_there_is_nothing_to_be_done(self):
        years = schedule.open_years(TODAY)
        assert years[-1] == 2026
        assert len(years) == 4


class TestReminders:
    SETTINGS = {"enabled": True, "days_before": [7, 3, 1, 0]}

    def test_silent_unless_switched_on(self):
        # Checked before anything else, so a shop that has not opted in cannot
        # receive one through a later branch.
        assert reminders.due_reminders(items_for(), {"enabled": False, "days_before": [7]}, TODAY) == []
        assert reminders.due_reminders(items_for(), {}, TODAY) == []
        assert reminders.due_reminders(items_for(), None, TODAY) == []

    def test_silent_when_every_offset_has_been_removed(self):
        assert reminders.due_reminders(items_for(), {"enabled": True, "days_before": []}, TODAY) == []

    def test_fires_on_the_chosen_offsets_only(self):
        # August's GSTR-1 is due today, so the zero-day step fires.
        due = reminders.due_reminders(items_for(), self.SETTINGS, TODAY)
        keys = {r.key for r in due}
        assert "082026:GSTR1:0" in keys

    def test_one_step_fires_not_every_step_that_has_passed(self):
        # Firing every offset whose day has gone would mean four notifications
        # on the due date, which is the fatigue this design exists to avoid.
        due = reminders.due_reminders(items_for(), self.SETTINGS, TODAY)
        august = [r for r in due if r.period == "082026" and r.kind == GSTR1]
        assert len(august) == 1

    def test_the_tone_escalates_as_the_date_approaches(self):
        completion = {
            (p, k): {"is_done": True}
            for p in ("042026", "052026", "062026", "072026", "082026")
            for k in (GSTR1, GSTR3B)
        }
        items = items_for(completion=completion)
        # September's GSTR-1 is due 2026-10-11.
        tones = {}
        for offset in (7, 3, 1, 0):
            day = date(2026, 10, 11) - timedelta(days=offset)
            fired = reminders.due_reminders(items, self.SETTINGS, day)
            match = next(r for r in fired if r.period == "092026" and r.kind == GSTR1)
            tones[offset] = match.tone
        assert tones[7] == "NOTE"
        assert tones[3] == "WARNING"
        assert tones[1] == "URGENT"
        assert tones[0] == "URGENT"

    def test_an_overdue_return_keeps_reminding_on_one_key(self):
        due = reminders.due_reminders(items_for(), self.SETTINGS, TODAY)
        overdue = [r for r in due if r.tone == "OVERDUE"]
        assert overdue
        assert len({r.key for r in overdue}) == len(overdue)
        assert all(r.key.endswith(":OVERDUE") for r in overdue)

    def test_an_approaching_bar_overrides_the_chosen_offsets(self):
        # A return weeks from being unfileable matters more than the schedule,
        # and fires whatever offsets were picked.
        due = reminders.due_reminders(items_for(fy=2023), self.SETTINGS, TODAY)
        final = [r for r in due if r.tone == "FINAL"]
        assert final
        assert "last window" in final[0].message

    def test_nothing_is_sent_about_a_return_that_can_no_longer_be_filed(self):
        due = reminders.due_reminders(items_for(fy=2022), self.SETTINGS, TODAY)
        assert due == []

    def test_the_most_pressing_comes_first(self):
        due = reminders.due_reminders(items_for(fy=2023) + items_for(), self.SETTINGS, TODAY)
        assert due[0].tone == "FINAL"

    def test_a_message_names_what_is_blocking(self):
        items = items_for()
        for item in items:
            item.blocking_count = 2
        due = reminders.due_reminders(items, self.SETTINGS, TODAY)
        assert any("2 items are still blocking it" in r.message for r in due)

    def test_preview_shows_the_volume_before_anybody_opts_in(self):
        # The honest way to answer "will this be annoying" is to show the
        # actual count rather than describe it.
        upcoming = reminders.preview(items_for(), {"days_before": [7, 3, 1, 0]}, TODAY, 20)
        assert upcoming
        assert all("would_fire_on" in r for r in upcoming)


class TestTimeline:
    def base(self, **kwargs):
        defaults = dict(
            period_state={"status": "OPEN"},
            gstr1_validation={"blocking": [], "warnings": []},
            sale_count=12, draft_count=0,
            gstr1_filing=None, gstr3b_filing=None,
        )
        defaults.update(kwargs)
        return stages.build(**defaults)

    def by_id(self, built):
        return {s.id: s for s in built}

    def test_has_all_eight_stages_in_order(self):
        assert [s.id for s in self.base()] == list(stages.STAGE_ORDER)

    def test_exactly_one_stage_is_the_one_to_work_on(self):
        built = self.base()
        working = [s for s in built if s.state in (stages.CURRENT,)
                   and s.id not in (stages.RECONCILED_2B, stages.IMS_ACTIONED)]
        assert len(working) == 1
        assert working[0].id == stages.PERIOD_CLOSED

    def test_capture_is_done_once_there_are_sales(self):
        assert self.by_id(self.base())[stages.SALES_CAPTURED].state == stages.DONE

    def test_a_nil_period_still_counts_as_captured(self):
        # Nothing was sold, and a nil return is still due - so capture is not
        # the thing holding it up.
        built = self.base(sale_count=0, is_nil_return=True)
        assert self.by_id(built)[stages.SALES_CAPTURED].state == stages.DONE

    def test_closing_advances_the_timeline(self):
        built = self.base(period_state={
            "status": "CLOSED", "closed_at": "2026-10-01T00:00:00Z",
            "payload_json": "{}",
        })
        found = self.by_id(built)
        assert found[stages.PERIOD_CLOSED].state == stages.DONE
        assert found[stages.GSTR1_PREPARED].state == stages.DONE
        assert found[stages.GSTR1_FILED].state == stages.CURRENT

    def test_recording_an_arn_completes_the_filing_stage(self):
        built = self.base(
            period_state={"status": "CLOSED", "payload_json": "{}"},
            gstr1_filing={"id": "f1", "arn": "AA270926000001X",
                          "filed_at": "2026-10-09T10:00:00Z", "payload_json": "{}"},
        )
        stage = self.by_id(built)[stages.GSTR1_FILED]
        assert stage.state == stages.DONE
        assert stage.evidence["arn"] == "AA270926000001X"
        assert stage.evidence["has_payload"] is True

    def test_the_filing_stage_says_this_app_does_not_file(self):
        stage = self.by_id(self.base())[stages.GSTR1_FILED]
        assert "does not file for you" in stage.detail

    def test_2b_and_ims_are_blocked_on_something_external(self):
        found = self.by_id(self.base())
        assert found[stages.RECONCILED_2B].state == stages.BLOCKED
        assert "not connected" in found[stages.RECONCILED_2B].detail
        assert found[stages.IMS_ACTIONED].state == stages.BLOCKED

    def test_a_stage_nobody_can_take_does_not_stall_the_rest(self):
        # 2B cannot be done at all yet; letting it hold the timeline would
        # leave every period stuck on a step with no button.
        built = self.base(period_state={"status": "CLOSED", "payload_json": "{}"},
                          gstr1_filing={"id": "f", "arn": "A" * 15, "filed_at": "x"})
        assert stages.current_stage(built).id == stages.GSTR3B_FILED

    def test_blocking_items_land_on_the_stage_they_belong_to(self):
        built = self.base(gstr1_validation={
            "blocking": [
                {"code": "SERIES_GAP", "message": "a gap"},
                {"code": "NO_UQC", "message": "no unit"},
            ],
            "warnings": [{"code": "DRAFT_IN_PERIOD", "message": "a draft"}],
        })
        found = self.by_id(built)
        assert [b["code"] for b in found[stages.SALES_CAPTURED].blocking] == ["SERIES_GAP"]
        assert [b["code"] for b in found[stages.GSTR1_PREPARED].blocking] == ["NO_UQC"]
        assert [w["code"] for w in found[stages.SALES_CAPTURED].warnings] == ["DRAFT_IN_PERIOD"]

    def test_an_unrecognised_code_falls_to_the_close(self):
        # That is where the engine refuses on it, so that is where somebody
        # will be looking.
        built = self.base(gstr1_validation={
            "blocking": [{"code": "SOMETHING_NEW", "message": "?"}], "warnings": [],
        })
        assert self.by_id(built)[stages.PERIOD_CLOSED].blocking[0]["code"] == "SOMETHING_NEW"

    def test_a_blocked_stage_reports_blocked_rather_than_current(self):
        built = self.base(gstr1_validation={
            "blocking": [{"code": "NO_GSTIN", "message": "no gstin"}], "warnings": [],
        })
        assert self.by_id(built)[stages.PERIOD_CLOSED].state == stages.BLOCKED

    def test_every_stage_links_to_where_the_work_is_done(self):
        # "3 blocking items" that somebody then has to go hunting for is worse
        # than no answer.
        assert all(s.link for s in self.base())
