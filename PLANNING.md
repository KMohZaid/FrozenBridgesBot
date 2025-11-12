# FrozenBridgesBot Rewrite Plan

## Executive Summary
Complete rewrite of core game state management and voting system to fix critical bugs and implement proper turn-based gameplay with timers.

---

## Current Issues Identified

### 1. Voting System Bug: 1 Negative Vote Balances 3+ Positive Votes
**Root Cause:** Likely allowing negative votes to subtract from positive vote count instead of treating them separately.

**Location:** `bot/game.py` - `add_vote()` method and vote counting logic

**Current Logic:**
- 60% threshold of active players required
- Votes stored as dict: `{user_id: VoteChoice.YES/NO}`
- Vote outcome calculated by counting yes votes vs threshold

**Issue:** Need to verify vote counting doesn't allow "no" votes to cancel "yes" votes.

### 2. After `/skipbridge` User Can No Longer Answer Questions
**Root Cause:** State not properly reset after skip, or player marked inactive incorrectly affects answering logic.

**Location:**
- `bot/plugins/callback_handlers.py` line 155: `skipped_player.is_active = False`
- `bot/plugins/voting.py`: `skip_turn_logic()`

**Issue:** Player becomes inactive when skipped, which may prevent them from being selected as answerer in future turns.

### 3. If Asker Leaves, Bot Assigns Next Player But Keeps Same Question
**Root Cause:** `next_turn()` doesn't reset `game.question` and `game.answer` state when current player leaves.

**Location:**
- `bot/game.py` lines 113-123: `next_turn()` method
- `bot/plugins/game_management.py` lines 240-248: Leave handler

**Issue:** Question/answer state should be cleared when questioner leaves.

### 4. Turn Management Index Bug
**Root Cause:** Turn index arithmetic breaks when players become inactive but remain in `self.players` list.

**Issue:** Using indices on a list with inactive players causes skipped turns or stuck turns.

### 5. No Timers for Game Actions
**Current State:** Only vote timeout exists (60s)

**Missing:**
- Question asking timeout
- Answer timeout
- Inactivity detection
- Auto-skip/auto-giveup

---

## Proposed Solutions

### Phase 1: Voting System Rewrite

#### New Vote Requirements
**Formula:** `required_votes = (active_players // 2) + 1`

**Examples:**
- 2 players: (2//2) + 1 = 2 votes (100%)
- 3 players: (3//2) + 1 = 2 votes (67%)
- 4 players: (4//2) + 1 = 3 votes (75%)
- 5 players: (5//2) + 1 = 3 votes (60%)
- 6 players: (6//2) + 1 = 4 votes (67%)

#### Vote Counting Logic
```python
def calculate_vote_outcome(self):
    active_count = len(self.active_players)
    required = (active_count // 2) + 1

    yes_votes = sum(1 for v in self.votes.values() if v == VoteChoice.YES)
    no_votes = sum(1 for v in self.votes.values() if v == VoteChoice.NO)

    # Vote passes if yes votes reach threshold
    if yes_votes >= required:
        return VoteOutcome.PASSED

    # Vote fails if impossible to reach threshold
    remaining = active_count - len(self.votes)
    if yes_votes + remaining < required:
        return VoteOutcome.FAILED_IMPOSSIBLE

    return VoteOutcome.ONGOING
```

**Key Change:** "No" votes don't cancel "yes" votes - they just count toward total votes cast.

#### Admin Force Skip
- New command: `/adminskip @user` or `/adminskip` (reply to message)
- Admin-only (configurable admin list)
- Bypasses voting system entirely
- Immediately skips target player's turn
- Works on current player or any future player

**Implementation:**
```python
@app.on_message(filters.command("adminskip") & filters.group)
async def admin_skip_command(client, message):
    # Check if user is admin
    if not is_admin(message.from_user.id, message.chat.id):
        return

    # Get target player (from reply or mention)
    target_player = get_target_player(message)

    # Force skip without vote
    await force_skip_player(client, game, target_player)
```

---

### Phase 2: Timer System Implementation

#### Timer Configuration
```python
# Timers (in seconds)
ASKING_TIMER_MIN = 60      # 1 minute minimum
ASKING_TIMER_MAX = 1800    # 30 minutes maximum
ASKING_TIMER_DEFAULT = 180 # 3 minutes default

ANSWERING_TIMER = 120      # 2 minutes for answering
DICE_ROLL_TIMER = 60       # 1 minute for dice roll
ACCEPT_REJECT_TIMER = 120  # 2 minutes to accept/reject answer

# Per-game configurable (admin setting)
class GameTimers:
    asking_timeout: int = ASKING_TIMER_DEFAULT
    answering_timeout: int = ANSWERING_TIMER
```

#### Timer Implementation Strategy

**1. Question Asking Timer**
```python
async def start_asking_timer(game, timeout):
    """Auto-skip if player doesn't ask question in time"""
    await asyncio.sleep(timeout)

    if game.game_state == GameState.PLAYING:
        # Still waiting for question
        await timeout_current_player(game)
```

**2. Answering Timer**
```python
async def start_answering_timer(game, timeout):
    """Auto-reject if answerer doesn't respond in time"""
    await asyncio.sleep(timeout)

    if game.game_state == GameState.ANSWERING:
        # Still waiting for answer
        await timeout_answer(game)
```

**3. Dice Roll Timer**
```python
async def start_dice_roll_timer(game, player_type, timeout):
    """Auto-roll dice if player doesn't roll in time"""
    await asyncio.sleep(timeout)

    if game.game_state == GameState.ROLLING:
        # Auto-roll for player
        await auto_roll_dice(game, player_type)
```

**Timer Management:**
- Store timer task in game object: `game.active_timer`
- Cancel previous timer before starting new one
- Clean up timers on game end

#### Admin Timer Configuration
```python
@app.on_message(filters.command("settimer") & filters.group)
async def set_timer_command(client, message):
    # /settimer asking 5  (sets asking timer to 5 minutes)
    # /settimer answering 2 (sets answering timer to 2 minutes)

    if not is_admin(message.from_user.id, message.chat.id):
        return

    # Validate and set timer
    # Max 30 minutes for asking, max 2 minutes for answering
```

---

### Phase 3: State Management Overhaul

#### Problem: Index-Based Turn Tracking
**Current:**
```python
turn_index: int
players: List[Player]  # Contains active and inactive

next_turn():
    for i in range(1, len(self.players) + 1):
        next_index = (self.turn_index + i) % len(self.players)
        if self.players[next_index].is_active:
            ...
```

**Issue:** When players become inactive, index arithmetic breaks.

#### Solution: Active Player Queue
**New Approach:**
```python
class Game:
    all_players: Dict[int, Player]  # {user_id: Player}
    active_player_queue: List[int]  # [user_id, user_id, ...]
    current_player_id: Optional[int]
    answerer_id: Optional[int]

    @property
    def active_players(self) -> List[Player]:
        return [self.all_players[uid] for uid in self.active_player_queue]

    @property
    def current_player(self) -> Optional[Player]:
        return self.all_players.get(self.current_player_id)

    @property
    def answerer(self) -> Optional[Player]:
        return self.all_players.get(self.answerer_id)
```

**Turn Advancement:**
```python
def next_turn(self):
    """Get next player in active queue"""
    if not self.active_player_queue:
        # No active players - end game
        return None

    if self.current_player_id is None:
        # First turn
        self.current_player_id = self.active_player_queue[0]
    else:
        # Find current player in queue
        try:
            current_idx = self.active_player_queue.index(self.current_player_id)
            next_idx = (current_idx + 1) % len(self.active_player_queue)
            self.current_player_id = self.active_player_queue[next_idx]
        except ValueError:
            # Current player not in queue (left game)
            self.current_player_id = self.active_player_queue[0]

    # Clear turn state
    self.clear_turn_state()

    return self.current_player
```

**Player Management:**
```python
def add_player(self, user):
    """Add new player or reactivate existing"""
    if user.id in self.all_players:
        # Player rejoining
        if user.id not in self.active_player_queue:
            self.active_player_queue.append(user.id)
    else:
        # New player
        player = Player(user)
        self.all_players[user.id] = player
        self.active_player_queue.append(user.id)

def remove_player(self, user_id):
    """Make player inactive"""
    if user_id in self.active_player_queue:
        self.active_player_queue.remove(user_id)

    # Keep in all_players for stats
    if user_id in self.all_players:
        self.all_players[user_id].is_active = False
```

#### State Reset on Player Leave
```python
def clear_turn_state(self):
    """Reset all turn-specific state"""
    self.question = None
    self.answer = None
    self.answerer_id = None
    self.current_player_roll = None
    self.answerer_roll = None
    self.game_state = GameState.PLAYING

    # Cancel any active timers
    if self.active_timer:
        self.active_timer.cancel()
        self.active_timer = None

def handle_player_leave(self, user_id):
    """Handle player leaving during their turn"""
    is_current = (user_id == self.current_player_id)
    is_answerer = (user_id == self.answerer_id)

    self.remove_player(user_id)

    if is_current:
        # Current player left - clear state and advance
        self.clear_turn_state()
        self.next_turn()
    elif is_answerer:
        # Answerer left - reset to asking state
        self.answerer_id = None
        self.answer = None
        self.game_state = GameState.PLAYING

    # Check if game should end
    if len(self.active_player_queue) <= 1:
        self.end_game()
```

---

### Phase 4: Turn Flow Refinement

#### Proper 2-Turn System: Questioner → Answerer

**Turn States:**
1. **PLAYING** - Current player can ask a question
2. **ANSWERING** - Selected player must answer
3. **ROLLING** - Both players roll dice
4. **RESOLVING** - Questioner accepts/rejects answer
5. **VOTING** - Vote in progress

**Turn Flow:**
```
START TURN (PLAYING state)
├─ Current player clicks "Ask a Player" button
├─ Select answerer from player list
├─ [TIMER: Asking timeout starts]
├─ Enter question via inline query
│
├─ Question submitted
├─ Clear asking timer
├─ State → ANSWERING
├─ [TIMER: Answering timeout starts]
├─ Notify answerer
│
├─ Answerer provides answer via inline query
├─ Clear answering timer
├─ State → ROLLING
├─ Both players roll dice
├─ [TIMER: Roll timeout for each player]
│
├─ Both rolled
├─ State → RESOLVING
├─ [TIMER: Accept/reject timeout]
├─ Questioner accepts or rejects
│
├─ IF ACCEPTED:
│   ├─ Answerer gets point
│   ├─ Update database stats
│   └─ Advance to next turn
│
├─ IF REJECTED:
│   └─ Advance to next turn (no points)
│
END TURN (call next_turn())
```

#### Timer Integration Points

**1. Asking Phase Timeout:**
```python
# After "Ask a Player" clicked, start timer
game.active_timer = asyncio.create_task(
    asking_timeout_task(client, game, game.timers.asking_timeout)
)

async def asking_timeout_task(client, game, timeout):
    await asyncio.sleep(timeout)

    if game.game_state == GameState.PLAYING and game.current_player_id:
        # Player didn't ask question in time
        await send_message(
            client,
            game.chat_id,
            f"{game.current_player.mention} took too long to ask! Skipping turn..."
        )

        game.clear_turn_state()
        game.next_turn()
        await send_turn_start_message(client, game)
```

**2. Answering Phase Timeout:**
```python
# After question submitted, start timer
game.active_timer = asyncio.create_task(
    answering_timeout_task(client, game, game.timers.answering_timeout)
)

async def answering_timeout_task(client, game, timeout):
    await asyncio.sleep(timeout)

    if game.game_state == GameState.ANSWERING and game.answerer_id:
        # Answerer didn't respond in time
        await send_message(
            client,
            game.chat_id,
            f"{game.answerer.mention} took too long to answer! Turn ended."
        )

        game.clear_turn_state()
        game.next_turn()
        await send_turn_start_message(client, game)
```

**3. Dice Roll Timeout:**
```python
# After answer submitted, both players need to roll
# Start separate timer for each

async def wait_for_rolls(client, game):
    """Wait for both players to roll, with timeout"""
    timeout = game.timers.dice_roll_timeout
    start_time = time.time()

    while game.game_state == GameState.ROLLING:
        await asyncio.sleep(1)
        elapsed = time.time() - start_time

        if elapsed >= timeout:
            # Auto-roll for players who didn't roll
            if game.current_player_roll is None:
                game.current_player_roll = random.randint(1, 6)
                await send_message(
                    client,
                    game.chat_id,
                    f"{game.current_player.mention} didn't roll - auto-rolled: {game.current_player_roll}"
                )

            if game.answerer_roll is None:
                game.answerer_roll = random.randint(1, 6)
                await send_message(
                    client,
                    game.chat_id,
                    f"{game.answerer.mention} didn't roll - auto-rolled: {game.answerer_roll}"
                )

            # Move to resolution
            game.game_state = GameState.RESOLVING
            await send_accept_reject_message(client, game)
            break
```

---

### Phase 5: Additional Fixes

#### Fix 1: Skip Only Affects Current Player
**Clarification:** Should `/skipbridge` only work on current player, or any player?

**Recommendation:** Two separate commands:
- `/skipbridge` - Vote to skip current player's turn (only works during their turn)
- `/votekick @player` - Vote to remove any player from game entirely

**Implementation:**
```python
# Skip current turn
if vote_type == VoteType.SKIP:
    # Only current player can be skipped
    target = game.current_player

    # Make inactive temporarily or permanently?
    # Option A: Skip this turn only (don't mark inactive)
    game.clear_turn_state()
    game.next_turn()

    # Option B: Remove from active queue (mark inactive)
    game.remove_player(target.user_id)
    game.clear_turn_state()
    game.next_turn()
```

#### Fix 2: State Validation
Add validation before each action:

```python
def validate_can_ask_question(game, user_id):
    """Check if user can ask question"""
    if game.game_state != GameState.PLAYING:
        return False, "Not in asking phase"

    if game.current_player_id != user_id:
        return False, "Not your turn"

    if game.question is not None:
        return False, "Question already asked"

    return True, None

def validate_can_answer(game, user_id):
    """Check if user can answer"""
    if game.game_state != GameState.ANSWERING:
        return False, "Not in answering phase"

    if game.answerer_id != user_id:
        return False, "Not the answerer"

    if game.answer is not None:
        return False, "Answer already provided"

    return True, None
```

#### Fix 3: Proper Message Cleanup
```python
class Game:
    # Track all message IDs for cleanup
    lobby_message_id: Optional[int]
    player_list_message_id: Optional[int]
    turn_message_id: Optional[int]
    vote_message_id: Optional[int]

    async def cleanup_messages(self, client):
        """Delete all game messages"""
        for msg_id in [self.lobby_message_id, self.player_list_message_id,
                       self.turn_message_id, self.vote_message_id]:
            if msg_id:
                try:
                    await client.delete_messages(self.chat_id, msg_id)
                except:
                    pass
```

---

## Implementation Order

### Sprint 1: Core State Management (Priority: CRITICAL)
**Goal:** Fix turn management and state bugs

**Tasks:**
1. [ ] Refactor `Game` class to use active player queue instead of index
2. [ ] Implement `clear_turn_state()` method
3. [ ] Update `next_turn()` to use queue-based approach
4. [ ] Fix player join/leave to update active queue
5. [ ] Add state validation functions
6. [ ] Test turn advancement with players leaving/joining

**Files to Modify:**
- `bot/game.py` (major refactor)
- `bot/plugins/game_management.py` (join/leave handlers)
- `bot/plugins/game_flow.py` (turn advancement)

**Success Criteria:**
- ✓ Turn advances correctly when players leave
- ✓ No duplicate turns
- ✓ State resets when current player leaves
- ✓ Players can rejoin without breaking turn order

---

### Sprint 2: Voting System Fix (Priority: HIGH)
**Goal:** Implement proper vote counting

**Tasks:**
1. [ ] Update vote threshold formula to `(active_players // 2) + 1`
2. [ ] Fix vote counting to not let "no" votes cancel "yes" votes
3. [ ] Add admin force skip command
4. [ ] Update vote UI to show correct required count
5. [ ] Test voting with various player counts

**Files to Modify:**
- `bot/game.py` (`add_vote()` method)
- `bot/plugins/voting.py` (vote logic)
- `bot/plugins/callback_handlers.py` (vote handlers)
- `bot/plugins/admin.py` (admin commands)

**Success Criteria:**
- ✓ 1 "no" vote doesn't cancel 3 "yes" votes
- ✓ Vote threshold follows (P/2)+1 formula
- ✓ Admins can force skip without vote
- ✓ Vote UI displays correct requirements

---

### Sprint 3: Timer System (Priority: HIGH)
**Goal:** Add timeouts for all game phases

**Tasks:**
1. [ ] Create timer configuration class
2. [ ] Implement asking phase timer (1-30 min configurable, default 3 min)
3. [ ] Implement answering phase timer (2 min)
4. [ ] Implement dice roll timer (1 min with auto-roll)
5. [ ] Implement accept/reject timer (2 min)
6. [ ] Add admin command to configure timers
7. [ ] Add timer cancellation on state changes
8. [ ] Add visual timer display in messages

**Files to Create:**
- `bot/timers.py` (timer management)

**Files to Modify:**
- `bot/game.py` (timer tracking)
- `bot/plugins/game_flow.py` (timer integration)
- `bot/plugins/admin.py` (timer config command)
- All handler files (timer starts/stops)

**Success Criteria:**
- ✓ Auto-skip if player doesn't ask in time
- ✓ Auto-reject if answerer doesn't respond
- ✓ Auto-roll if players don't roll dice
- ✓ Admins can configure timer lengths
- ✓ Timers properly cancelled on state changes

---

### Sprint 4: Polish & Testing (Priority: MEDIUM)
**Goal:** Ensure all fixes work together

**Tasks:**
1. [ ] Add comprehensive state validation
2. [ ] Improve error messages
3. [ ] Add logging for debugging
4. [ ] Test all edge cases:
   - [ ] Multiple players leaving during turn
   - [ ] Vote during answering phase
   - [ ] Timer expiry during vote
   - [ ] All players but one leaving
   - [ ] Player rejoining after skip
5. [ ] Update help messages and commands
6. [ ] Add unit tests (optional but recommended)

**Files to Modify:**
- All plugin files (error handling)
- `bot/plugins/utils.py` (helper functions)

**Success Criteria:**
- ✓ No crashes under any scenario
- ✓ Clear error messages
- ✓ All edge cases handled gracefully
- ✓ Help text reflects new features

---

## Migration Strategy

### Option A: In-Place Refactor (Recommended)
**Pros:** Keep git history, gradual changes
**Cons:** More complex, need to maintain working state

**Approach:**
1. Create feature branch: `git checkout -b refactor-state-management`
2. Implement Sprint 1 (state management)
3. Test thoroughly
4. Merge to main
5. Repeat for Sprints 2-4

### Option B: Clean Rewrite
**Pros:** Start fresh, cleaner code
**Cons:** Lose git history, more disruptive

**Approach:**
1. Create new branch: `git checkout -b v2-rewrite`
2. Copy working files to new structure
3. Implement all sprints
4. Test entire system
5. Merge when complete

**Recommendation:** Use Option A (in-place refactor) to maintain working bot during development.

---

## Decisions Made

### 1. Skip Behavior ✓
**Decision:** When `/skipbridge` vote passes, player becomes **inactive until they rejoin**
- Player is marked `is_active = False`
- They're removed from active player queue
- They can use `/joinbridge` to return anytime
- Game continues without blocking

**Admin Skip:**
- Admins can use `/adminskip` to force skip without voting
- Works the same way (makes player inactive)

---

### 2. Timer Configuration ✓
**Decision:** **Configurable by admins** via `/settimer` command

**Default Timer Lengths:**
- Asking: 3 minutes (configurable 1-30 min)
- Answering: 2 minutes (configurable 1-5 min)
- Dice roll: 1 minute (fixed, with auto-roll)
- Accept/reject: 2 minutes (configurable 1-5 min)

**Admin Command:**
```
/settimer asking 5     # Set asking timer to 5 minutes
/settimer answering 2  # Set answering timer to 2 minutes
/settimer accept 3     # Set accept/reject timer to 3 minutes
/settimer reset        # Reset to defaults
```

**Maximum Limits:**
- Asking: 30 minutes max
- Answering: 5 minutes max
- Accept/reject: 5 minutes max
- Total turn time: Up to 40 minutes max (if all set to max)

---

### 3. Admin Permissions ✓
**Decision:** **Telegram group admins + Bot owner**

**Implementation:**
```python
async def is_admin(user_id: int, chat_id: int, client: Client) -> bool:
    # Check if bot owner
    if user_id == BOT_OWNER_ID:
        return True

    # Check if Telegram group admin
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in [
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR
        ]
    except:
        return False
```

---

### 4. Vote Commands ✓
**Decision:** **Two separate commands**

**Commands:**
1. **`/skipbridge [@user]`** - Makes player inactive until they rejoin
   - If used on current player: Vote to skip their turn
   - If used on other player: Vote to make them inactive
   - Player can return with `/joinbridge`
   - Requires (P/2)+1 votes

2. **`/votekick @user`** - Permanently removes player from game
   - Player is completely removed from game
   - Cannot rejoin with `/joinbridge`
   - Must wait for new game
   - Requires (P/2)+1 votes

**Admin versions:**
- `/adminskip @user` - Force skip without vote
- `/adminkick @user` - Force remove without vote

---

### 5. State Persistence
**Decision:** **Future feature, not in initial refactor**
- Focus on fixing core bugs first
- Add database persistence in v2.0

---

### 6. Turn Timer Style
**Decision:** **Each phase has separate timer** (configurable)
- Asking timer runs independently
- Answering timer runs independently
- Rolling and accepting have their own timers
- Total turn time = sum of all phases

---

## Testing Checklist

### State Management Tests
- [ ] Turn advances correctly with all players active
- [ ] Turn advances when current player leaves
- [ ] Turn advances when answerer leaves
- [ ] Turn order maintained when player rejoins
- [ ] No crashes when all players leave except one
- [ ] State resets when current player leaves mid-turn
- [ ] Question cleared when asker leaves

### Voting Tests
- [ ] Vote passes with (P/2)+1 yes votes
- [ ] Vote fails when not enough yes votes
- [ ] "No" votes don't cancel "yes" votes
- [ ] Vote with 2 players requires 2 yes votes
- [ ] Vote with 5 players requires 3 yes votes
- [ ] Admin force skip works
- [ ] Vote timeout works
- [ ] Can't vote twice

### Timer Tests
- [ ] Asking timer expires and skips turn
- [ ] Answering timer expires and ends turn
- [ ] Dice roll timer expires and auto-rolls
- [ ] Accept/reject timer expires and ends turn
- [ ] Timer cancelled when action completed
- [ ] Timer cancelled when player leaves
- [ ] Timer configurable by admin

### Edge Cases
- [ ] Vote started then player leaves
- [ ] Timer expires during vote
- [ ] Player leaves during dice roll
- [ ] Two players leave simultaneously
- [ ] Skip vote on inactive player
- [ ] Join game while vote in progress

---

## File Structure After Refactor

```
bot/
├── __main__.py           # Bot initialization
├── game.py              # Core Game class (MAJOR REFACTOR)
├── database.py          # Database operations
├── timers.py            # NEW: Timer management
├── config.py            # NEW: Configuration constants
└── plugins/
    ├── game_management.py    # Lobby, join/leave (MODERATE CHANGES)
    ├── game_flow.py         # Turn flow, dice rolling (MAJOR CHANGES)
    ├── voting.py            # Voting system (MAJOR CHANGES)
    ├── callback_handlers.py # Button handlers (MODERATE CHANGES)
    ├── inline_handlers.py   # Inline queries (MINOR CHANGES)
    ├── admin.py             # Admin commands (NEW COMMANDS)
    ├── giveup.py            # Give up command (MINOR CHANGES)
    ├── playerlist.py        # Player list (MINOR CHANGES)
    ├── stats.py             # Statistics (NO CHANGES)
    └── utils.py             # Helper functions (NEW HELPERS)
```

---

## Risk Assessment

### High Risk
- **State management refactor** - Core system change, high chance of bugs
- **Turn advancement logic** - Critical path, affects all gameplay

**Mitigation:** Extensive testing, incremental rollout

### Medium Risk
- **Timer system** - New feature, integration points throughout codebase
- **Voting formula change** - Changes game balance

**Mitigation:** Feature flags, easy revert

### Low Risk
- **Admin commands** - Isolated feature
- **Message cleanup** - Quality of life, not critical

**Mitigation:** Standard testing

---

## Success Metrics

### Functionality
- ✓ All 3 reported bugs fixed
- ✓ No crashes during normal gameplay
- ✓ Turn order always correct
- ✓ State always consistent

### Performance
- ✓ Turn transitions < 2 seconds
- ✓ Bot responsive during votes
- ✓ Memory usage stable (no leaks)

### User Experience
- ✓ Clear error messages
- ✓ Intuitive timer displays
- ✓ Fair voting system
- ✓ Smooth gameplay flow

---

## Additional Feature Decisions

### 7. Difficulty-Based Scoring System ✓
**Decision:** **5-star difficulty rating** chosen after answer is given

**Implementation:**
- When questioner accepts/rejects answer, they also rate difficulty (1-5 stars)
- Points awarded = difficulty rating (1-5 points)
- If rejected, no points awarded regardless of difficulty
- Default difficulty if not rated: 3 stars (medium)

**UI Flow:**
```
Question: "What is the capital of France?"
Answer: "Paris"

Accept/Reject buttons:
[✅ Accept] [❌ Reject]

After accepting:
Rate difficulty:
[⭐] [⭐⭐] [⭐⭐⭐] [⭐⭐⭐⭐] [⭐⭐⭐⭐⭐]
 1pt   2pt    3pt      4pt       5pt
```

---

### 8. Timer Configuration ✓
**Decision:** **2 minutes for asking, 3 minutes for answering** (configurable by admin)

**Default Timers:**
- Asking: 2 minutes (questioner has less time to think)
- Answering: 3 minutes (answerer needs more time)
- Dice roll: 1 minute (auto-roll if timeout)
- Accept/reject + difficulty rating: 2 minutes

**Timer Warnings:**
- Send warning message at: **1 minute left**
- Send warning message at: **30 seconds left**
- Send warning message at: **10 seconds left**

**Example:**
```
[At 1:00 remaining]
⏰ @user - 1 minute left to ask your question!

[At 0:30 remaining]
⏰ @user - 30 seconds left!

[At 0:10 remaining]
⚠️ @user - 10 seconds left!

[At 0:00]
⏱️ Time's up! @user took too long. Skipping turn...
```

**Timeout Behavior:**
- **Asking timeout:** Skip turn, advance to next player
- **Answering timeout:** Auto-reject answer, end turn
- **Dice roll timeout:** Auto-roll dice for player(s)
- **Accept/reject timeout:** Auto-accept answer (answerer gets points)

---

### 9. Timer Display ✓
**Decision:** Send messages at intervals (not live countdown)

**Implementation:**
- Don't edit messages constantly
- Send new warning messages at key intervals
- Simple format: "⏰ X minutes/seconds left!"

---

### 10. End Game Summary ✓
**Decision:** Show **full scoreboard + game statistics**

**Implementation:**
```
🎮 Game Ended! 🎮

📊 Final Scoreboard:
1. 🥇 @player1 - 15 points
2. 🥈 @player2 - 12 points
3. 🥉 @player3 - 8 points
4. @player4 - 5 points

📈 Game Statistics:
• Total Questions: 24
• Total Time: 1h 23m
• Total Players: 6
• Most Active: @player1 (8 questions)
• Hardest Question: 5⭐ by @player2
• Longest Answer: 247 characters by @player3

Thanks for playing! 🎉
```

---

### 11. Statistics Commands ✓
**Decision:** Add **/mystats** and **/leaderboard** commands

**Commands:**
1. **`/mystats`** - Show personal statistics
   ```
   📊 Your Statistics

   🎮 Games Played: 47
   🏆 Games Won: 12 (26%)

   ❓ Questions Asked: 132
   ✅ Questions Answered: 145
   ⭐ Average Difficulty: 3.2

   🎯 Acceptance Rate: 78%
   📈 Total Points: 387
   🔥 Best Streak: 7 in a row

   🏅 Best Game: 18 points
   📅 Last Played: 2 hours ago
   ```

2. **`/leaderboard`** - Show top players (global)
   ```
   🏆 Global Leaderboard 🏆

   1. 👑 @player1 - 2,453 pts (89 games)
   2. 🥈 @player2 - 2,102 pts (76 games)
   3. 🥉 @player3 - 1,876 pts (93 games)
   4. @player4 - 1,654 pts (54 games)
   5. @player5 - 1,432 pts (67 games)

   Your rank: #12 (387 points)
   ```

---

### 12. Feedback System ✓
**Decision:** Add **/feedback** command to submit feedback

**Implementation:**
```python
@app.on_message(filters.command("feedback"))
async def feedback_command(client, message):
    # Usage: /feedback Your message here

    if len(message.command) < 2:
        await message.reply("Usage: /feedback <your message>")
        return

    feedback_text = message.text.split(maxsplit=1)[1]
    user = message.from_user

    # Send to bot owner
    await client.send_message(
        BOT_OWNER_ID,
        f"📢 Feedback from {user.mention} (ID: {user.id})\n"
        f"Group: {message.chat.title} (ID: {message.chat.id})\n\n"
        f"{feedback_text}"
    )

    await message.reply("✅ Feedback sent! Thank you!")
```

---

### 13. Vote Transparency ✓
**Decision:** **Show who voted yes/no during the vote**

**Implementation:**
- Vote message updates in real-time showing who voted
- Format:
  ```
  🗳️ Vote to skip @player

  Required: 3 votes (of 5 players)

  ✅ Yes (2): @voter1, @voter2
  ❌ No (1): @voter3

  [✅ Yes] [❌ No]

  Time left: 45 seconds
  ```

---

### 14. Content Limits ✓
**Decision:** **No length limits** on questions/answers

**Inline Query Optimization:**
- Remove `chat_id` and other metadata from inline results
- Give users maximum space to type
- Current inline result format may include unnecessary data

**TODO:** Investigate and optimize inline query implementation to maximize text input space

---

### 15. Dice Animation Fix ✓
**Decision:** **Investigate current implementation first**

**Issue:** Dice not showing animated on iPhone/PC

**TODO:**
- Check how dice rolls are currently sent
- Test on different platforms (iPhone, PC, Android)
- Determine if it's using Telegram's native dice feature or custom implementation
- Fix animation if possible

---

### 16. Game End Condition ✓
**Decision:** **Auto-end game when only 1 player remains**

**Implementation:**
- After any player leave, check active player count
- If `len(active_players) <= 1`, trigger game end
- Show end game summary even if forced end
- Winner is last remaining player

---

### 17. Player Visibility ✓
**Decision:** **Inactive players can see everything** (spectator mode)

**Reasoning:**
- Game is group-based, everyone in chat can see messages
- No need to hide game from inactive players
- They can watch and potentially rejoin later

---

### 18. Turn Transfer ✓
**Decision:** **Only via skip/vote system** (no direct transfer)

**Reasoning:**
- Use existing `/skipbridge` for skipping turns
- Admins can use `/adminskip` to force skip
- Keeps game flow simple and predictable

---

### 19. Achievements ✓
**Decision:** **Future feature (v2.0)**

**Examples for later:**
- 🎯 "Sharp Shooter" - Accept 10 answers in a row
- 🧠 "Einstein" - Answer 5 five-star questions correctly
- 🎲 "Lucky" - Roll three 6s in a row
- 👑 "Champion" - Win 10 games

---

### 20. Anti-Abuse Measures ✓
**Decision:** **Add to planning, discuss options**

**Potential Measures:**
1. **Vote spam protection:** Each player can only initiate 1 vote per game
2. **Rejoin cooldown:** Can't rejoin for X seconds after leaving
3. **Question spam filter:** Detect duplicate/spam questions
4. **Rate limiting:** Limit how often players can join/leave games
5. **Trust Telegram moderation:** Rely on group admins to ban/mute abusers

**TODO:** Discuss which measures to implement in Sprint 4

---

## Summary of All Decisions

### ✅ Confirmed Features

**Core Fixes:**
- Voting formula: (P/2)+1
- Skip makes inactive (can rejoin)
- Fix state management and turn tracking
- Show who voted in real-time

**Scoring:**
- 5-star difficulty rating (1-5 points)
- Rating chosen after answer given
- Auto-accept on timeout (answerer gets points)

**Timers:**
- Asking: 2 minutes (default)
- Answering: 3 minutes (default)
- Dice roll: 1 minute (auto-roll)
- Accept/reject: 2 minutes (auto-accept)
- Warnings at: 1min, 30sec, 10sec
- Configurable by admins via `/settimer`

**Commands:**
- `/skipbridge @user` - Vote to skip (inactive until rejoin)
- `/votekick @user` - Vote to permanently remove
- `/adminskip @user` - Force skip (admin only)
- `/adminkick @user` - Force remove (admin only)
- `/settimer` - Configure timers (admin only)
- `/mystats` - Personal statistics
- `/leaderboard` - Global rankings
- `/feedback <message>` - Submit feedback

**Admin Permissions:**
- Telegram group admins + bot owner

**Game Rules:**
- Minimum 2 players
- Auto-end if 1 player remains
- No game duration/round limits
- No Q&A length limits

**UI/UX:**
- End game: Full scoreboard + statistics
- No DM notifications
- Timer warnings via messages
- Vote transparency (show who voted)

**Future Features (v2.0):**
- Achievements/badges
- State persistence (database)
- Anti-abuse measures (TBD)

---

## Technical TODOs

1. **Optimize inline queries** - Remove chat_id to maximize typing space
2. **Investigate dice animation** - Fix animation on iPhone/PC
3. **Anti-abuse measures** - Determine which to implement
4. **Performance testing** - Ensure bot handles multiple concurrent games
5. **Logging system** - Add comprehensive logging for debugging

---

## Updated Timeline Estimate

**Sprint 1 (State Management):** 2-3 days
- Fix turn tracking with player queue
- Fix state clearing on player leave
- Add state validation

**Sprint 2 (Voting System):** 2-3 days
- Fix vote counting: (P/2)+1 formula
- Add vote transparency (show who voted)
- Add `/adminskip`, `/adminkick`, `/votekick` commands
- Add admin permission checking

**Sprint 3 (Timer System):** 3-4 days
- Implement timer system with warnings
- Add configurable timers via `/settimer`
- Add auto-skip/auto-accept/auto-roll on timeout
- Update default timers: 2min ask, 3min answer

**Sprint 4 (Scoring & Stats):** 2-3 days
- Add 5-star difficulty rating system
- Update scoring logic
- Add `/mystats` and `/leaderboard` commands
- Update database schema for new stats

**Sprint 5 (Polish & New Features):** 2-3 days
- Add end game summary (scoreboard + statistics)
- Add `/feedback` command
- Optimize inline queries
- Investigate and fix dice animation
- Add comprehensive error handling

**Sprint 6 (Testing & Anti-Abuse):** 2-3 days
- Test all edge cases
- Implement selected anti-abuse measures
- Performance testing
- Bug fixes and polish

**Total:** 13-19 days of focused development

---

## Next Steps

1. ✅ **Gather all requirements** - COMPLETED
2. ✅ **Document all decisions** - COMPLETED
3. **Set up development environment** - Create test bot
4. **Begin Sprint 1** - State management refactor
5. **Iterative development** - Complete sprints sequentially
6. **Testing after each sprint** - Ensure stability
7. **Deploy and monitor** - Production rollout

---

## Notes

- Prioritize Sprints 1-3 (core fixes) before Sprints 4-6 (new features)
- Can deploy after Sprint 3 if needed (core functionality working)
- Sprints 4-6 are enhancements and can be added later
- Consider creating a staging/test group for testing before production
- Keep old code in git branches in case rollback needed
